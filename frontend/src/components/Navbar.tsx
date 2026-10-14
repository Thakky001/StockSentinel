/**
 * Navbar – Top navigation bar for StockSentinel.
 *
 * Features:
 * - Branding logo
 * - Scan date selector (populated from /api/screener/dates)
 * - "Run Scan" button with spinner when scan is active
 * - Watchlist icon button with item count badge
 * - Position Calculator button
 */

import React, { useEffect, useState } from 'react';
import { fetchScreenerDates } from '../api/screenerApi.ts';
import { useScanStatus } from '../hooks/useScanStatus.ts';

interface NavbarProps {
  selectedDate: string;
  onDateChange: (date: string) => void;
  watchlistCount: number;
  onWatchlistOpen: () => void;
  onCalculatorOpen: () => void;
}

const Navbar: React.FC<NavbarProps> = ({
  selectedDate,
  onDateChange,
  watchlistCount,
  onWatchlistOpen,
  onCalculatorOpen,
}) => {
  const [dates, setDates] = useState<string[]>([]);
  const [datesError, setDatesError] = useState<string | null>(null);
  const { isRunning, triggerScan, loading: scanLoading, error: scanError } = useScanStatus();

  useEffect(() => {
    fetchScreenerDates()
      .then(setDates)
      .catch((err: unknown) => {
        setDatesError(err instanceof Error ? err.message : 'ไม่สามารถโหลดรายการวันที่ได้');
      });
  }, []);

  const handleRunScan = async () => {
    if (isRunning || scanLoading) return;
    await triggerScan();
  };

  return (
    <nav className="sticky top-0 z-40 bg-slate-900/95 backdrop-blur border-b border-slate-700/60 shadow-lg">
      <div className="container mx-auto px-4 h-14 flex items-center gap-4">
        {/* Logo */}
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-xl">🛡️</span>
          <span className="font-bold text-slate-100 text-lg tracking-tight">
            Stock<span className="text-blue-400">Sentinel</span>
          </span>
        </div>

        {/* Divider */}
        <div className="h-6 w-px bg-slate-700 hidden sm:block" />

        {/* Scan date selector */}
        <div className="flex items-center gap-2">
          <label htmlFor="scan-date" className="text-xs text-slate-400 hidden md:block">
            วันที่สแกน
          </label>
          {datesError ? (
            <span className="text-xs text-rose-400">{datesError}</span>
          ) : (
            <select
              id="scan-date"
              value={selectedDate}
              onChange={(e) => onDateChange(e.target.value)}
              className="bg-slate-800 border border-slate-600 text-slate-100 text-sm rounded-md px-2 py-1 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent min-w-[120px]"
            >
              <option value="">รอบล่าสุด</option>
              {dates.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Scan error */}
        {scanError && (
          <span className="text-xs text-rose-400 hidden md:block max-w-[200px] truncate">
            {scanError}
          </span>
        )}

        {/* Run Scan button */}
        <button
          onClick={handleRunScan}
          disabled={isRunning || scanLoading}
          title={isRunning ? 'กำลังสแกนหุ้น...' : 'เริ่มสแกนหุ้นรอบใหม่'}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-400 text-white text-sm font-medium px-3 py-1.5 rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {isRunning || scanLoading ? (
            <>
              {/* Spinner */}
              <svg
                className="animate-spin h-4 w-4 text-white"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="hidden sm:inline">กำลังสแกน...</span>
            </>
          ) : (
            <>
              <span>▶</span>
              <span className="hidden sm:inline">สแกนหุ้น</span>
            </>
          )}
        </button>

        {/* Position Calculator button */}
        <button
          onClick={onCalculatorOpen}
          title="เครื่องคำนวณขนาดไม้ & บริหารความเสี่ยง"
          className="flex items-center gap-1.5 bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm font-medium px-3 py-1.5 rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <span className="text-base">🧮</span>
          <span className="hidden md:inline">คำนวณพอร์ต</span>
        </button>

        {/* Watchlist button */}
        <button
          onClick={onWatchlistOpen}
          title="เปิดรายการหุ้นที่บันทึกไว้"
          className="relative flex items-center gap-1.5 bg-slate-700 hover:bg-slate-600 text-slate-100 text-sm font-medium px-3 py-1.5 rounded-md transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <span className="text-base">⭐</span>
          <span className="hidden md:inline">หุ้นที่บันทึก</span>
          {watchlistCount > 0 && (
            <span className="absolute -top-1.5 -right-1.5 bg-blue-500 text-white text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center px-1">
              {watchlistCount > 99 ? '99+' : watchlistCount}
            </span>
          )}
        </button>
      </div>
    </nav>
  );
};

export default Navbar;
