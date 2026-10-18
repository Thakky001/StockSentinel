/**
 * ChartModal – Modal popup displaying interactive TradingView candlestick chart
 * with 30-week SMA, volume histogram, and Weinstein breakout price overlays.
 */

import React, { useEffect, useState } from 'react';
import type { ChartData, ScreenerSignal } from '../types/index.ts';
import { fetchStockChart } from '../api/screenerApi.ts';
import TradingViewChart from './TradingViewChart.tsx';
import StatusBadge from './StatusBadge.tsx';

interface ChartModalProps {
  ticker: string | null;
  onClose: () => void;
}

const ChartModal: React.FC<ChartModalProps> = ({ ticker, onClose }) => {
  const [chartData, setChartData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Close on Escape key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Fetch chart data when ticker changes
  useEffect(() => {
    if (!ticker) {
      setChartData(null);
      return;
    }

    let isMounted = true;
    setLoading(true);
    setError(null);

    fetchStockChart(ticker, 104)
      .then((data) => {
        if (isMounted) setChartData(data);
      })
      .catch((err) => {
        if (isMounted) {
          setError(err instanceof Error ? err.message : 'ไม่สามารถโหลดข้อมูลกราฟได้');
        }
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [ticker]);

  if (!ticker) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fadeIn">
      {/* Backdrop click to close */}
      <div className="absolute inset-0" onClick={onClose} />

      {/* Modal Dialog Card */}
      <div className="relative w-full max-w-5xl bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl overflow-hidden z-10 flex flex-col max-h-[92vh]">
        {/* Header */}
        <div className="flex items-center justify-between p-4 sm:p-5 border-b border-slate-800 bg-slate-900/90">
          <div className="flex items-center gap-3">
            <h2 className="text-xl sm:text-2xl font-bold text-slate-100 font-mono tracking-tight">
              {ticker}
            </h2>
            {chartData && (
              <>
                <span className="text-sm sm:text-base text-slate-400 font-normal truncate max-w-xs sm:max-w-md">
                  {chartData.company_name}
                </span>
                <StatusBadge status={chartData.metrics.status as ScreenerSignal['status']} />
              </>
            )}
          </div>

          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-100 hover:bg-slate-800 w-8 h-8 rounded-lg flex items-center justify-center text-lg transition-colors focus:outline-none"
            title="ปิด (Esc)"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="p-4 sm:p-5 overflow-y-auto space-y-4">
          {/* Key Metrics Strip */}
          {chartData?.metrics && (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <div className="bg-slate-800/80 border border-slate-700/60 rounded-xl p-3 text-center">
                <span className="text-xs text-slate-400 block mb-0.5">จุดเข้าซื้อ (Pivot)</span>
                <span className="text-base sm:text-lg font-mono font-bold text-emerald-400">
                  ${chartData.metrics.entry_price.toFixed(2)}
                </span>
              </div>

              <div className="bg-slate-800/80 border border-slate-700/60 rounded-xl p-3 text-center">
                <span className="text-xs text-slate-400 block mb-0.5">เพดานซื้อ (+5%)</span>
                <span className="text-base sm:text-lg font-mono font-bold text-amber-400">
                  ${chartData.metrics.max_buy_price.toFixed(2)}
                </span>
              </div>

              <div className="bg-slate-800/80 border border-slate-700/60 rounded-xl p-3 text-center">
                <span className="text-xs text-slate-400 block mb-0.5">จุดตัดขาดทุน (SL)</span>
                <span className="text-base sm:text-lg font-mono font-bold text-rose-400">
                  ${chartData.metrics.stop_loss_price.toFixed(2)}
                </span>
              </div>

              <div className="bg-slate-800/80 border border-slate-700/60 rounded-xl p-3 text-center">
                <span className="text-xs text-slate-400 block mb-0.5">ราคาปิดล่าสุด</span>
                <span className="text-base sm:text-lg font-mono font-bold text-slate-100">
                  ${chartData.metrics.close_price.toFixed(2)}
                </span>
              </div>
            </div>
          )}

          {/* Chart or Loading / Error State */}
          {loading && (
            <div className="h-[450px] flex flex-col items-center justify-center bg-slate-950/50 rounded-lg border border-slate-800">
              <div className="animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mb-3" />
              <p className="text-sm text-slate-400">กำลังโหลดแท่งเทียนรายสัปดาห์ & ตัวชี้วัดทางเทคนิค...</p>
            </div>
          )}

          {error && (
            <div className="h-[450px] flex flex-col items-center justify-center bg-slate-950/60 rounded-xl border border-amber-500/30 p-8 text-center space-y-3">
              <div className="w-14 h-14 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mx-auto text-2xl">
                📊
              </div>
              <h3 className="text-lg font-semibold text-slate-200">
                {error.includes('ไม่พบประวัติราคา') ? 'ไม่พบประวัติราคา กรุณาซิงก์ข้อมูล' : 'ไม่สามารถโหลดข้อมูลกราฟได้'}
              </h3>
              <p className="text-xs sm:text-sm text-slate-400 max-w-md">
                {error.includes('ไม่พบประวัติราคา')
                  ? `ระบบยังไม่มีข้อมูลแท่งเทียนราคาจริงสำหรับหุ้น ${ticker} ในฐานข้อมูล กรุณารันซิงก์ข้อมูล (Daily Sync) เพื่อดาวน์โหลดประวัติราคาจริง`
                  : error}
              </p>
            </div>
          )}

          {!loading && !error && (!chartData || !chartData.candlesticks || chartData.candlesticks.length === 0) && (
            <div className="h-[450px] flex flex-col items-center justify-center bg-slate-950/60 rounded-xl border border-amber-500/30 p-8 text-center space-y-3">
              <div className="w-14 h-14 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mx-auto text-2xl">
                📊
              </div>
              <h3 className="text-lg font-semibold text-slate-200">ไม่พบประวัติราคา กรุณาซิงก์ข้อมูล</h3>
              <p className="text-xs sm:text-sm text-slate-400 max-w-md">
                ระบบยังไม่มีข้อมูลแท่งเทียนราคาจริงสำหรับหุ้น {ticker} ในฐานข้อมูล กรุณารันซิงก์ข้อมูล (Daily Sync) เพื่อดาวน์โหลดประวัติราคาจริง
              </p>
            </div>
          )}

          {!loading && !error && chartData && chartData.candlesticks.length > 0 && (
            <TradingViewChart data={chartData} height={460} />
          )}
        </div>
      </div>
    </div>
  );
};

export default ChartModal;
