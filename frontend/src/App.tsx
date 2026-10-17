/**
 * StockSentinel – Main Frontend Web Application
 * React 18 + Vite + Tailwind CSS + TradingView Lightweight Charts
 */

import React, { useState, useMemo, useCallback } from 'react';
import Navbar from './components/Navbar.tsx';
import FilterBar from './components/FilterBar.tsx';
import ScreenerTable from './components/ScreenerTable.tsx';
import Pagination from './components/Pagination.tsx';
import ChartModal from './components/ChartModal.tsx';
import WatchlistDrawer from './components/WatchlistDrawer.tsx';
import PositionCalculator from './components/PositionCalculator.tsx';
import { useScreenerData } from './hooks/useScreener.ts';
import { useWatchlist } from './hooks/useWatchlist.ts';
import type { ScreenerSignal, ScreenerFilters } from './types/index.ts';

const App: React.FC = () => {
  // Navigation & Scan Date State
  const [selectedDate, setSelectedDate] = useState<string>('');

  // Position Sizing State
  const [portfolioSize, setPortfolioSize] = useState<number>(10000);
  const [riskPct, setRiskPct] = useState<number>(1.0);

  // Filter & Search State
  const [search, setSearch] = useState<string>('');
  const [sector, setSector] = useState<string>('');
  const [status, setStatus] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('quality_score');
  const [order, setOrder] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState<number>(1);
  const limit = 50;

  // Dialog & Modal State
  const [chartTicker, setChartTicker] = useState<string | null>(null);
  const [showWatchlist, setShowWatchlist] = useState<boolean>(false);
  const [showCalculator, setShowCalculator] = useState<boolean>(false);
  const [calcInitialEntry, setCalcInitialEntry] = useState<number>(100);
  const [calcInitialStop, setCalcInitialStop] = useState<number>(92);

  // Watchlist custom hook (synced with localStorage)
  const {
    watchlist,
    addToWatchlist,
    removeFromWatchlist,
    isWatchlisted,
    clearWatchlist,
  } = useWatchlist();

  // Memoized query filter payload for API hook
  const filters: ScreenerFilters = useMemo(
    () => ({
      date: selectedDate || undefined,
      sector: sector || undefined,
      status: status || undefined,
      search: search.trim() || undefined,
      sort_by: sortBy,
      order: order,
      page: page,
      limit: limit,
    }),
    [selectedDate, sector, status, search, sortBy, order, page, limit]
  );

  // Screener Data Hook
  const { signals, loading, error, total, totalPages, scanDate, marketRegime } = useScreenerData(filters);

  // Derive unique sectors from returned signals for dropdown suggestions
  const availableSectors = useMemo(() => {
    const set = new Set<string>();
    if (Array.isArray(signals)) {
      signals.forEach((s) => {
        if (s && s.sector && s.sector !== 'Unknown' && s.sector !== 'N/A') {
          set.add(s.sector);
        }
      });
    }
    return Array.from(set).sort();
  }, [signals]);

  // Handle column sort toggle
  const handleSortChange = useCallback((column: string) => {
    setSortBy((prevSort) => {
      if (prevSort === column) {
        setOrder((prevOrder) => (prevOrder === 'asc' ? 'desc' : 'asc'));
        return prevSort;
      } else {
        setOrder(column === 'diff_pct' ? 'asc' : 'desc');
        return column;
      }
    });
    setPage(1);
  }, []);

  // Handle status filter change + auto-sort
  const handleStatusChange = useCallback((newStatus: string) => {
    setStatus(newStatus);
    setPage(1);

    if (newStatus === 'IN_BUY_ZONE') {
      setSortBy('quality_score');
      setOrder('desc');
    } else if (!newStatus) {
      setSortBy('quality_score');
      setOrder('desc');
    }
  }, []);

  // Handle search text change
  const handleSearchChange = useCallback((newSearch: string) => {
    setSearch((prev) => {
      if (prev !== newSearch) {
        setPage(1);
        return newSearch;
      }
      return prev;
    });
  }, []);

  // Handle sector change
  const handleSectorChange = useCallback((newSector: string) => {
    setSector(newSector);
    setPage(1);
  }, []);

  // Handle date change
  const handleDateChange = useCallback((newDate: string) => {
    setSelectedDate(newDate);
    setPage(1);
  }, []);

  // Handle page change
  const handlePageChange = useCallback((newPage: number) => {
    setPage(newPage);
  }, []);

  // Handle adding/removing from watchlist
  const handleToggleWatchlist = (sig: ScreenerSignal) => {
    if (isWatchlisted(sig.ticker)) {
      removeFromWatchlist(sig.ticker);
    } else {
      addToWatchlist(sig);
    }
  };

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col font-sans selection:bg-blue-500 selection:text-white">
      {/* Top Navbar */}
      <Navbar
        selectedDate={selectedDate}
        onDateChange={handleDateChange}
        watchlistCount={watchlist.length}
        onWatchlistOpen={() => setShowWatchlist(true)}
        onCalculatorOpen={() => {
          setCalcInitialEntry(100);
          setCalcInitialStop(92);
          setShowCalculator(true);
        }}
      />

      {/* Main Content Area */}
      <main className="flex-1 container mx-auto px-4 py-6 max-w-7xl">
        {/* Dashboard Header Title & Subtitle */}
        <div className="mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-slate-800 pb-4">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-100 flex items-center gap-2">
              <span>ระบบสแกนหุ้น Stan Weinstein Stage 2 (V2.0)</span>
            </h1>
            <p className="text-xs sm:text-sm text-slate-400 mt-1">
              ระบบสแกนหุ้นสหรัฐฯ อัตโนมัติในดัชนี S&P 500 คัดกรองจุดเบรกเอาต์ 35 สัปดาห์ (Pivot 35w), 
              ฐานราคาบีบตัว (Tightness &le; 18%), โวลุ่มระเบิดตัว &ge; 1.5 เท่า, เส้น 30w ชี้ขึ้น, และ Mansfield RS ขาขึ้นชนะ SPY
            </p>
          </div>

          {scanDate && (
            <div className="text-xs bg-slate-800 border border-slate-700/80 px-3 py-1.5 rounded-lg text-slate-300 self-start sm:self-auto font-mono whitespace-nowrap shrink-0">
              วันที่สแกน: <b className="text-blue-400 whitespace-nowrap">{scanDate.includes('T') ? scanDate.split('T')[0] : scanDate}</b>
            </div>
          )}
        </div>

        {/* Market Regime Filter Banner */}
        {marketRegime === 'BEAR_MARKET' && (
          <div className="mb-6 bg-rose-950/80 border-2 border-rose-500 text-rose-100 rounded-xl p-4 flex items-center gap-4 shadow-lg animate-pulse">
            <span className="text-3xl">🛑</span>
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-base sm:text-lg font-bold text-rose-200">
                  Market in Correction - งดเปิดสถานะซื้อใหม่ หรือลดขนาดไม้ลง 50%
                </h2>
                <span className="text-[11px] bg-rose-500/30 text-rose-200 px-2 py-0.5 rounded font-mono font-bold">
                  BEAR_MARKET
                </span>
              </div>
              <p className="text-xs text-rose-300/90 mt-1">
                ดัชนี S&P 500 (SPY) หลุดต่ำกว่าเส้นค่าเฉลี่ย 30 สัปดาห์ (SMA 30w) สภาวะตลาดมีความเสี่ยงสูงต่อการเกิด False Breakout
              </p>
            </div>
          </div>
        )}

        {marketRegime === 'CAUTION_MARKET' && (
          <div className="mb-6 bg-amber-950/60 border border-amber-600/80 text-amber-100 rounded-xl p-4 flex items-center gap-4 shadow-md">
            <span className="text-3xl">⚠️</span>
            <div className="flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-base font-bold text-amber-200">
                  สภาวะตลาด: เฝ้าระวังความผันผวน (Market in Caution)
                </h2>
                <span className="text-[11px] bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded font-mono font-bold border border-amber-500/30">
                  CAUTION_MARKET
                </span>
              </div>
              <p className="text-xs text-amber-300/90 mt-1">
                ดัชนี SPY หลุดต่ำกว่าเส้น SMA 10 สัปดาห์ หรือความชัน SMA 30w ชะลอตัว แนะนำลดขนาดไม้ลง 30-50% และเลือกเฉพาะหุ้นที่มี Mansfield RS แข็งแกร่งที่สุด
              </p>
            </div>
          </div>
        )}

        {marketRegime === 'BULL_MARKET' && (
          <div className="mb-6 bg-emerald-950/50 border border-emerald-600/70 text-emerald-100 rounded-xl p-3.5 flex items-center justify-between shadow-sm">
            <div className="flex items-center gap-3">
              <span className="text-2xl">🟢</span>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-bold text-sm text-emerald-300">
                    สภาวะตลาด: ตลาดกระทิงขาขึ้นสมบูรณ์ (Bull Market Regime)
                  </span>
                  <span className="text-[10px] bg-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded font-mono font-bold">
                    BULL_MARKET
                  </span>
                </div>
                <p className="text-xs text-emerald-400/90 mt-0.5">
                  ดัชนี SPY ยืนเหนือเส้น SMA 30 สัปดาห์และความชันเป็นบวก สภาวะตลาดเอื้ออำนวยต่อการ Breakout อย่างเต็มที่
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Global Error Notice */}
        {error && (
          <div className="mb-6 bg-rose-950/70 border border-rose-800 text-rose-300 text-sm rounded-xl p-4 flex items-center gap-3">
            <span className="text-xl">⚠️</span>
            <div className="flex-1">
              <span className="font-semibold block">ไม่สามารถโหลดข้อมูลสแกนหุ้นได้</span>
              <span className="text-xs text-rose-400">{error}</span>
            </div>
          </div>
        )}

        {/* Filter Bar */}
        <FilterBar
          search={search}
          onSearchChange={handleSearchChange}
          sector={sector}
          onSectorChange={handleSectorChange}
          status={status}
          onStatusChange={handleStatusChange}
          availableSectors={availableSectors}
        />

        {/* Position Sizing & Risk Management Controls */}
        <div className="mb-4 bg-slate-800/60 border border-slate-700/60 rounded-xl p-3 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex items-center gap-2 text-slate-300">
            <span className="text-base">🛡️</span>
            <span className="font-semibold text-slate-200">การตั้งค่าพอร์ต & บริหารความเสี่ยง (Position Sizing):</span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-1.5 bg-slate-900/80 px-2.5 py-1.5 rounded-lg border border-slate-700/80">
              <span className="text-slate-400">ขนาดพอร์ต:</span>
              <span className="text-slate-400 font-mono">$</span>
              <input
                type="number"
                min="1000"
                step="1000"
                value={portfolioSize}
                onChange={(e) => setPortfolioSize(Math.max(100, Number(e.target.value) || 0))}
                className="w-20 bg-transparent text-slate-100 font-mono font-semibold focus:outline-none"
              />
            </div>

            <div className="flex items-center gap-1.5 bg-slate-900/80 px-2.5 py-1.5 rounded-lg border border-slate-700/80">
              <span className="text-slate-400">เสี่ยงต่อไม้:</span>
              <input
                type="number"
                min="0.1"
                max="10"
                step="0.25"
                value={riskPct}
                onChange={(e) => setRiskPct(Math.max(0.1, Number(e.target.value) || 0))}
                className="w-12 bg-transparent text-slate-100 font-mono font-semibold text-right focus:outline-none"
              />
              <span className="text-slate-400 font-mono">%</span>
            </div>

            <div className="flex items-center gap-1.5 bg-slate-900/80 px-2.5 py-1.5 rounded-lg border border-slate-700/80">
              <span className="text-slate-400">งบเสี่ยง/ไม้ (1R):</span>
              <span className="text-rose-400 font-mono font-bold">
                ${((portfolioSize * riskPct) / 100).toFixed(0)}
              </span>
            </div>

            <button
              onClick={() => {
                setCalcInitialEntry(100);
                setCalcInitialStop(92);
                setShowCalculator(true);
              }}
              className="bg-slate-700 hover:bg-slate-600 text-slate-200 px-3 py-1.5 rounded-lg font-medium transition-colors flex items-center gap-1"
            >
              <span>🧮</span>
              <span>เครื่องคำนวณละเอียด</span>
            </button>
          </div>
        </div>

        {/* Screener Signals Table */}
        <ScreenerTable
          signals={signals}
          loading={loading}
          sortBy={sortBy}
          order={order}
          portfolioSize={portfolioSize}
          riskPct={riskPct}
          onSortChange={handleSortChange}
          onOpenChart={(t) => setChartTicker(t)}
          onOpenCalculator={(entry, stop) => {
            setCalcInitialEntry(entry);
            setCalcInitialStop(stop);
            setShowCalculator(true);
          }}
          isWatchlisted={isWatchlisted}
          onToggleWatchlist={handleToggleWatchlist}
        />

        {/* Pagination Footer */}
        {!loading && (
          <Pagination
            page={page}
            totalPages={totalPages}
            total={total}
            limit={limit}
            onPageChange={handlePageChange}
          />
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800 bg-slate-950/60 py-4 text-center text-xs text-slate-500">
        <p>StockSentinel &copy; 2026 &bull; ระบบสแกนและวิเคราะห์หุ้นอัตโนมัติ ตามหลักการ Stan Weinstein Stage 2</p>
      </footer>

      {/* Interactive TradingView Chart Modal */}
      {chartTicker && (
        <ChartModal
          ticker={chartTicker}
          onClose={() => setChartTicker(null)}
        />
      )}

      {/* LocalStorage Watchlist Drawer */}
      <WatchlistDrawer
        isOpen={showWatchlist}
        onClose={() => setShowWatchlist(false)}
        watchlist={watchlist}
        onRemove={removeFromWatchlist}
        onClear={clearWatchlist}
        onViewChart={(t) => setChartTicker(t)}
      />

      {/* Risk & Position Sizing Calculator Modal */}
      <PositionCalculator
        isOpen={showCalculator}
        onClose={() => setShowCalculator(false)}
        initialEntryPrice={calcInitialEntry}
        initialStopLoss={calcInitialStop}
        initialAccountSize={portfolioSize}
        initialRiskPct={riskPct}
      />
    </div>
  );
};

export default App;
