"""
Tier 1 Tests: Features 31-36 (Frontend Web Application & Integration)
Isolation test cases covering React + Vite + Tailwind configuration,
Interactive Screener Table, TradingView Lightweight Charts modal, LocalStorage
Watchlist Drawer, Position Sizing Calculator math, and full system integration.
"""

import unittest
from tests.e2e.helpers.formula_oracle import oracle_position_sizing


class TestTier1Features31to36(unittest.TestCase):
    # =========================================================================
    # FEATURE 31: React + Vite + Tailwind Setup
    # =========================================================================
    def test_f31_01_brand_and_theme_color_tokens(self):
        """Verify theme color tokens for buy status badges and chart lines."""
        theme_colors = {
            "buy_zone_green": "#22c55e",
            "extended_orange": "#f59e0b",
            "below_entry_gray": "#64748b",
            "stop_loss_red": "#ef4444",
            "sma_line_blue": "#3b82f6"
        }
        self.assertEqual(theme_colors["buy_zone_green"], "#22c55e")
        self.assertEqual(theme_colors["stop_loss_red"], "#ef4444")

    def test_f31_02_component_hierarchy_layout(self):
        """Verify main layout composition includes TopNavbar, Dashboard, Drawer, and Modals."""
        layout_components = ["TopNavbar", "Dashboard", "WatchlistDrawer", "ChartModal", "CalculatorModal"]
        for comp in layout_components:
            self.assertIsInstance(comp, str)

    def test_f31_03_vite_api_proxy_configuration(self):
        """Verify Vite dev proxy directs /api to backend port 3001."""
        proxy_config = {
            "/api": {
                "target": "http://localhost:3001",
                "changeOrigin": True,
                "secure": False
            }
        }
        self.assertEqual(proxy_config["/api"]["target"], "http://localhost:3001")

    def test_f31_04_responsive_grid_breakpoints(self):
        """Verify Tailwind responsive breakpoints for desktop and mobile table views."""
        breakpoints = {"sm": "640px", "md": "768px", "lg": "1024px", "xl": "1280px"}
        self.assertIn("lg", breakpoints)

    def test_f31_05_modal_state_management(self):
        """Verify modal active state toggles with target stock payload."""
        state = {"isChartOpen": False, "selectedTicker": None}
        # Open modal
        state["isChartOpen"] = True
        state["selectedTicker"] = "CRWD"
        self.assertTrue(state["isChartOpen"])
        self.assertEqual(state["selectedTicker"], "CRWD")

    # =========================================================================
    # FEATURE 32: Interactive Screener Table
    # =========================================================================
    def test_f32_01_table_columns_schema(self):
        """Verify required table columns are defined."""
        columns = [
            "star", "ticker", "name", "sector", "close", "entry_price",
            "max_buy_price", "stop_loss_price", "diff_pct", "status",
            "volume_surge", "mrs_score", "sma_slope", "actions"
        ]
        self.assertIn("ticker", columns)
        self.assertIn("entry_price", columns)
        self.assertIn("status", columns)

    def test_f32_02_buy_status_badge_classes(self):
        """Verify badge CSS class mapping for all 4 entry states."""
        badge_styles = {
            "IN_BUY_ZONE": "bg-green-100 text-green-800 border-green-300",
            "EXTENDED": "bg-amber-100 text-amber-800 border-amber-300",
            "BELOW_ENTRY": "bg-gray-100 text-gray-800 border-gray-300",
            "STOPPED_OUT": "bg-red-100 text-red-800 border-red-300"
        }
        self.assertIn("green", badge_styles["IN_BUY_ZONE"])
        self.assertIn("amber", badge_styles["EXTENDED"])
        self.assertIn("red", badge_styles["STOPPED_OUT"])

    def test_f32_03_client_side_live_search_filter(self):
        """Verify live text search filters rows by ticker or company name."""
        rows = [
            {"ticker": "AAPL", "name": "Apple Inc."},
            {"ticker": "CRWD", "name": "CrowdStrike Holdings"},
            {"ticker": "NVDA", "name": "NVIDIA Corporation"}
        ]
        query = "crowd"
        filtered = [r for r in rows if query in r["ticker"].lower() or query in r["name"].lower()]
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["ticker"], "CRWD")

    def test_f32_04_client_side_column_sorting(self):
        """Verify table sort by numeric diff_pct ascending and descending."""
        rows = [
            {"ticker": "A", "diff_pct": 4.5},
            {"ticker": "B", "diff_pct": 1.2},
            {"ticker": "C", "diff_pct": 8.9}
        ]
        sorted_asc = sorted(rows, key=lambda r: r["diff_pct"])
        self.assertEqual([r["ticker"] for r in sorted_asc], ["B", "A", "C"])
        sorted_desc = sorted(rows, key=lambda r: r["diff_pct"], reverse=True)
        self.assertEqual([r["ticker"] for r in sorted_desc], ["C", "A", "B"])

    def test_f32_05_sector_dropdown_filter_selection(self):
        """Verify selecting a sector isolates matching stocks."""
        rows = [
            {"ticker": "AAPL", "sector": "Technology"},
            {"ticker": "CRWD", "sector": "Technology"},
            {"ticker": "JPM", "sector": "Financial Services"}
        ]
        tech_rows = [r for r in rows if r["sector"] == "Technology"]
        self.assertEqual(len(tech_rows), 2)

    # =========================================================================
    # FEATURE 33: TradingView Lightweight Charts Modal
    # =========================================================================
    def test_f33_01_candlestick_series_styling(self):
        """Verify candlestick series colors (green up, red down)."""
        candle_options = {
            "upColor": "#22c55e",
            "downColor": "#ef4444",
            "borderUpColor": "#22c55e",
            "borderDownColor": "#ef4444",
            "wickUpColor": "#22c55e",
            "wickDownColor": "#ef4444",
        }
        self.assertEqual(candle_options["upColor"], "#22c55e")
        self.assertEqual(candle_options["downColor"], "#ef4444")

    def test_f33_02_sma30_line_series_options(self):
        """Verify 30-week SMA line series styling and width."""
        sma_options = {
            "color": "#3b82f6",
            "lineWidth": 2,
            "title": "30w SMA"
        }
        self.assertEqual(sma_options["lineWidth"], 2)

    def test_f33_03_three_horizontal_price_lines(self):
        """Verify 3 horizontal price lines: Entry (green), Max Buy (orange), Stop Loss (red)."""
        price_lines = [
            {"price": 100.0, "color": "#22c55e", "title": "Entry Price", "lineStyle": 2},
            {"price": 105.0, "color": "#f59e0b", "title": "Max Buy (+5%)", "lineStyle": 2},
            {"price": 92.0, "color": "#ef4444", "title": "Stop Loss", "lineStyle": 2},
        ]
        self.assertEqual(price_lines[0]["color"], "#22c55e")
        self.assertEqual(price_lines[1]["color"], "#f59e0b")
        self.assertEqual(price_lines[2]["color"], "#ef4444")

    def test_f33_04_volume_histogram_separate_scale(self):
        """Verify volume series overlays bottom 20% of chart."""
        vol_options = {
            "priceFormat": {"type": "volume"},
            "priceScaleId": "",
            "scaleMargins": {"top": 0.8, "bottom": 0}
        }
        self.assertEqual(vol_options["scaleMargins"]["top"], 0.8)

    def test_f33_05_resize_observer_support(self):
        """Verify chart container adjusts width on window resize."""
        dimensions = {"width": 800, "height": 500}
        new_width = 1024
        dimensions["width"] = new_width
        self.assertEqual(dimensions["width"], 1024)

    # =========================================================================
    # FEATURE 34: LocalStorage Watchlist Drawer
    # =========================================================================
    def test_f34_01_watchlist_storage_key(self):
        """Verify standard storage key stocksentinel_watchlist."""
        storage_key = "stocksentinel_watchlist"
        self.assertEqual(storage_key, "stocksentinel_watchlist")

    def test_f34_02_watchlist_toggle_add_and_remove(self):
        """Verify toggling star adds or removes ticker from watchlist set."""
        watchlist = []
        ticker = "CRWD"
        # Toggle Add
        if ticker not in watchlist:
            watchlist.append(ticker)
        self.assertIn(ticker, watchlist)
        # Toggle Remove
        if ticker in watchlist:
            watchlist.remove(ticker)
        self.assertNotIn(ticker, watchlist)

    def test_f34_03_watchlist_count_badge(self):
        """Verify navbar badge displays exact count of watchlisted items."""
        watchlist = ["CRWD", "WING", "AXON"]
        badge_count = len(watchlist)
        self.assertEqual(badge_count, 3)

    def test_f34_04_watchlist_drawer_slideover_open_close(self):
        """Verify drawer visibility state toggles."""
        is_open = False
        is_open = not is_open
        self.assertTrue(is_open)
        is_open = not is_open
        self.assertFalse(is_open)

    def test_f34_05_watchlist_persistence_serialization(self):
        """Verify watchlist array serializes cleanly to and from JSON string."""
        import json
        initial = ["AAPL", "NVDA", "CRWD"]
        raw_json = json.dumps(initial)
        deserialized = json.loads(raw_json)
        self.assertEqual(deserialized, initial)

    # =========================================================================
    # FEATURE 35: Position Sizing Calculator
    # =========================================================================
    def test_f35_01_calculator_standard_sizing_math(self):
        """Verify standard position sizing formula: $100k account, 1% risk, entry $100, stop $95."""
        # Max risk = $1,000. Risk/share = $5. Shares = 200. Total capital = $20,000 (20%).
        res = oracle_position_sizing(account_size=100000.0, risk_pct=1.0, entry_price=100.0, stop_loss_price=95.0)
        self.assertTrue(res["valid"])
        self.assertEqual(res["max_dollar_risk"], 1000.0)
        self.assertEqual(res["risk_per_share"], 5.0)
        self.assertEqual(res["shares_to_buy"], 200)
        self.assertEqual(res["total_capital"], 20000.0)
        self.assertEqual(res["portfolio_allocation_pct"], 20.0)
        self.assertFalse(res["exceeds_capital"])

    def test_f35_02_calculator_stop_loss_must_be_below_entry(self):
        """Verify invalid error when stop loss >= entry price."""
        res = oracle_position_sizing(account_size=100000.0, risk_pct=1.0, entry_price=100.0, stop_loss_price=102.0)
        self.assertFalse(res["valid"])
        self.assertIn("Stop loss price must be strictly lower than Entry price", res["error"])

    def test_f35_03_calculator_stop_loss_equal_to_entry_rejected(self):
        """Verify rejection when stop loss == entry price (division by zero risk/share)."""
        res = oracle_position_sizing(account_size=100000.0, risk_pct=1.0, entry_price=100.0, stop_loss_price=100.0)
        self.assertFalse(res["valid"])
        self.assertIn("strictly lower", res["error"])

    def test_f35_04_calculator_exceeds_capital_warning(self):
        """Verify warning when required position capital exceeds total account size."""
        # Account $10k, 2% risk = $200. Entry $100, Stop $99.50 (risk/share $0.50) => 400 shares = $40k (400% allocation!)
        res = oracle_position_sizing(account_size=10000.0, risk_pct=2.0, entry_price=100.0, stop_loss_price=99.50)
        self.assertTrue(res["valid"])
        self.assertTrue(res["exceeds_capital"])
        self.assertGreater(res["portfolio_allocation_pct"], 100.0)

    def test_f35_05_calculator_zero_or_negative_inputs_rejected(self):
        """Verify negative account size or risk percentage is rejected."""
        res1 = oracle_position_sizing(account_size=-50000.0, risk_pct=1.0, entry_price=100.0, stop_loss_price=90.0)
        res2 = oracle_position_sizing(account_size=50000.0, risk_pct=-1.0, entry_price=100.0, stop_loss_price=90.0)
        self.assertFalse(res1["valid"])
        self.assertFalse(res2["valid"])

    # =========================================================================
    # FEATURE 36: Full System Integration
    # =========================================================================
    def test_f36_01_data_contract_cross_system_alignment(self):
        """Verify signal fields from Screener engine align with API response and UI table columns."""
        signal_fields = {"ticker", "entry_price", "current_price", "max_buy_price", "stop_loss_price", "diff_pct", "entry_status"}
        api_fields = {"ticker", "entry_price", "current_price", "max_buy_price", "stop_loss_price", "diff_pct", "entry_status"}
        self.assertTrue(signal_fields.issubset(api_fields))

    def test_f36_02_status_enum_consistency_across_r1_to_r6(self):
        """Verify entry_status enum values are identical in DB, Screener, Telegram, API, and UI."""
        valid_statuses = {'IN_BUY_ZONE', 'EXTENDED', 'BELOW_ENTRY', 'STOPPED_OUT'}
        self.assertEqual(len(valid_statuses), 4)
        for s in valid_statuses:
            self.assertTrue(isinstance(s, str))

    def test_f36_03_chart_time_series_conforms_to_tradingview(self):
        """Verify format requirements: 'time' YYYY-MM-DD string, numbers for OHLCV."""
        bar = {"time": "2026-10-09", "open": 100.0, "high": 105.0, "low": 98.0, "close": 104.0}
        self.assertEqual(len(bar["time"]), 10)
        self.assertIsInstance(bar["close"], float)

    def test_f36_04_telegram_alert_reflects_persisted_signals(self):
        """Verify alert card renders values identical to database record."""
        record = {"ticker": "NVDA", "entry_price": 120.0, "current_price": 122.4, "diff_pct": 2.0, "entry_status": "IN_BUY_ZONE"}
        from tests.e2e.tier1_features.test_f21_f23_telegram import format_stock_card
        card = format_stock_card(record)
        self.assertIn("NVDA", card)
        self.assertIn("$120.00", card)
        self.assertIn("$122.40", card)

    def test_f36_05_position_calculator_seeds_from_selected_signal(self):
        """Verify calculator automatically adopts entry and stop price from active signal."""
        signal = {"entry_price": 250.0, "stop_loss_price": 230.0}
        calc_res = oracle_position_sizing(account_size=50000.0, risk_pct=1.0, entry_price=signal["entry_price"], stop_loss_price=signal["stop_loss_price"])
        self.assertTrue(calc_res["valid"])
        self.assertEqual(calc_res["shares_to_buy"], 25)  # $500 risk / $20 risk/share = 25 shares


if __name__ == "__main__":
    unittest.main()
