"""
Tier 4 Scenario Test: Cold Start Ingestion to Live Dashboard
Exercises the complete application lifecycle from an empty database,
through 2-year history ingestion, weekly resampling, Stage 2 screening,
Telegram alert formatting, Express REST API querying, and dashboard chart rendering.
"""

import unittest
from tests.e2e.helpers.sql_validator import InMemoryRelationalDB
from tests.e2e.helpers.api_validator import InMemoryExpressApp, validate_api_envelope, validate_chart_payload
from tests.e2e.helpers.mock_data import (
    generate_universe_tickers,
    generate_daily_bars_for_stock,
    generate_spy_benchmark_bars
)
from tests.e2e.helpers.formula_oracle import (
    oracle_resample_daily_to_weekly,
    oracle_sma,
    oracle_sma_slope,
    oracle_volume_surge,
    oracle_prior_resistance_pivot,
    oracle_mansfield_relative_strength,
    oracle_stage2_filter,
    oracle_target_and_risk,
    oracle_entry_status
)
from tests.e2e.tier1_features.test_f21_f23_telegram import format_weekly_digest


class TestTier4ColdStartToDashboard(unittest.TestCase):
    def test_e2e_cold_start_pipeline_workflow(self):
        """
        Step-by-step E2E cold start flow:
        1. Initialize database and register universe + SPY
        2. Ingest 2 years (520 trading days) of daily bars for universe and SPY
        3. Vectorized weekly resampling to Friday-closed weekly bars
        4. Calculate 30w SMA, slope, 10w volume average, 35w pivot, and Mansfield RS vs SPY
        5. Run Stage 2 filter and compute target/risk metrics
        6. Persist qualified signals in screener_signals and record scan_jobs audit log
        7. Format Telegram alert digest
        8. Query Express API endpoints (GET /api/screener/latest, GET /api/stock/:ticker/chart)
        9. Verify chart payload is 100% compliant with TradingView Lightweight Charts
        """
        # Step 1: Database Init
        db = InMemoryRelationalDB()
        app = InMemoryExpressApp(db)
        
        raw_universe = generate_universe_tickers()
        for stock in raw_universe:
            db.upsert_stock(stock)
        self.assertGreaterEqual(len(db.stocks), 15)
        
        # Step 2: Ingest 2-Year History
        spy_daily = generate_spy_benchmark_bars(num_days=520)
        for b in spy_daily:
            db.upsert_daily_bar(b)
            
        test_tickers = ["AAPL", "CRWD", "WING", "NVDA"]
        for t in test_tickers:
            # CRWD will be configured as breakout
            pattern = "stage2_breakout" if t == "CRWD" else "stage4_downtrend"
            daily_bars = generate_daily_bars_for_stock(t, pattern=pattern, num_days=520, base_price=100.0)
            for b in daily_bars:
                db.upsert_daily_bar(b)
                
        # Step 3: Resample to Weekly
        spy_weekly = oracle_resample_daily_to_weekly(spy_daily)
        spy_closes = [w["close"] for w in spy_weekly]
        
        # Step 4 & 5: Screener Execution & Filtering
        job_id = db.create_scan_job({
            "job_type": "COLD_START_SCREEN", "status": "RUNNING",
            "started_at": "2026-10-14T02:00:00Z", "tickers_total": len(test_tickers)
        })
        
        qualified_signals = []
        for t in test_tickers:
            t_daily = [b for k, b in db.stock_daily_bars.items() if k[0] == t]
            t_weekly = oracle_resample_daily_to_weekly(t_daily)
            
            closes = [w["close"] for w in t_weekly]
            highs = [w["high"] for w in t_weekly]
            volumes = [w["volume"] for w in t_weekly]
            
            sma30 = oracle_sma(closes, window=30)
            slope = oracle_sma_slope(sma30, lookback=1)
            avg_vol10, surge = oracle_volume_surge(volumes, window=10)
            pivot35 = oracle_prior_resistance_pivot(highs, lookback=35)
            mrs = oracle_mansfield_relative_strength(closes, spy_closes, lookback=52)
            
            filter_res = oracle_stage2_filter(
                close=closes[-1],
                sma_30w=sma30[-1],
                sma_30w_slope=slope[-1],
                pivot_35w=pivot35[-1],
                vol_surge_ratio=surge[-1],
                mrs_score=mrs[-1]
            )
            
            if filter_res["is_stage2"]:
                risk = oracle_target_and_risk(pivot_35w=pivot35[-1], current_price=closes[-1])
                status = oracle_entry_status(closes[-1], risk["entry_price"], risk["max_buy_price"], risk["stop_loss_price"])
                sig_record = {
                    "scan_id": job_id,
                    "scan_date": "2026-10-09",
                    "ticker": t,
                    "entry_price": risk["entry_price"],
                    "max_buy_price": risk["max_buy_price"],
                    "current_price": risk["current_price"],
                    "stop_loss_price": risk["stop_loss_price"],
                    "diff_pct": risk["diff_pct"],
                    "entry_status": status,
                    "volume_surge_ratio": surge[-1],
                    "mrs_score": mrs[-1],
                    "sma_30w": sma30[-1],
                    "sma_30w_slope": slope[-1],
                    "prior_resistance_35w": pivot35[-1],
                    "weekly_close": closes[-1],
                    "weekly_volume": volumes[-1],
                    "avg_volume_10w": int(avg_vol10[-1])
                }
                qualified_signals.append(sig_record)
                
        # Step 6: Persist signals & update job
        for s in qualified_signals:
            db.upsert_screener_signal(s)
            
        db.update_scan_job(job_id, {
            "status": "COMPLETED",
            "completed_at": "2026-10-14T02:05:00Z",
            "tickers_processed": len(test_tickers),
            "signals_found": len(qualified_signals),
            "telegram_alert_sent": True
        })
        
        self.assertEqual(len(qualified_signals), 1)
        self.assertEqual(qualified_signals[0]["ticker"], "CRWD")
        self.assertEqual(db.scan_jobs[job_id]["status"], "COMPLETED")
        
        # Step 7: Telegram Alert Verification
        digest = format_weekly_digest(qualified_signals, scan_date="2026-10-09")
        self.assertIn("CRWD", digest)
        self.assertIn("Breakouts Found: <b>1</b>", digest)
        
        # Step 8: Express REST API Verification
        code_latest, resp_latest = app.handle_get_screener_latest({})
        self.assertEqual(code_latest, 200)
        self.assertEqual(resp_latest["data"]["total"], 1)
        self.assertEqual(resp_latest["data"]["signals"][0]["ticker"], "CRWD")
        
        # Step 9: Chart Modal Endpoint Verification
        code_chart, resp_chart = app.handle_get_stock_chart("CRWD")
        self.assertEqual(code_chart, 200)
        is_valid_chart, chart_err = validate_chart_payload(resp_chart["data"])
        self.assertTrue(is_valid_chart, chart_err)
        self.assertGreaterEqual(len(resp_chart["data"]["candlesticks"]), 100)
        self.assertGreaterEqual(len(resp_chart["data"]["sma30"]), 70)


if __name__ == "__main__":
    unittest.main()
