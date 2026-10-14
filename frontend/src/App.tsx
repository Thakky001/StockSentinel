/**
 * StockSentinel – Main Frontend Web Application
 * React 18 + Vite + Tailwind CSS + TradingView Lightweight Charts
 */

import React, { useState, useMemo } from 'react';
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

  // Filter & Search State
  const [search, setSearch] = useState<string>('');
  const [sector, setSector] = useState<string>('');
  const [status, setStatus] = useState<string>('');
  const [sortBy, setSortBy] = useState<string>('mrs_score');
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
  const { signals, loading, error, total, totalPages, scanDate } = useScreenerData(filters);

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
  const handleSortChange = (column: string) => {
    if (sortBy === column) {
      setOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortBy(column);
      setOrder('desc');
    }
    setPage(1);
  };

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
        onDateChange={(d) => {
          setSelectedDate(d);
          setPage(1);
        }}
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
              <span>ระบบสแกนหุ้น Stan Weinstein Stage 2</span>
            </h1>
            <p className="text-xs sm:text-sm text-slate-400 mt-1">
              ระบบสแกนหุ้นสหรัฐฯ อัตโนมัติกว่า 3,800 ตัว (Russell 3000 + S&P 1500) คัดกรองจุดเบรกเอาต์ (Breakout Pivot),
              โวลุ่มระเบิดตัว &ge; 1.5 เท่า, เส้นค่าเฉลี่ย 30 สัปดาห์ชี้ขึ้น และค่าความแข็งแกร่ง Mansfield RS ชนะตลาด (SPY)
            </p>
          </div>

          {scanDate && (
            <div className="text-xs bg-slate-800 border border-slate-700/80 px-3 py-1.5 rounded-lg text-slate-300 self-start sm:self-auto font-mono">
              วันที่สแกน: <b className="text-blue-400">{scanDate}</b>
            </div>
          )}
        </div>

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
          onSearchChange={(s) => {
            setSearch(s);
            setPage(1);
          }}
          sector={sector}
          onSectorChange={(sec) => {
            setSector(sec);
            setPage(1);
          }}
          status={status}
          onStatusChange={(st) => {
            setStatus(st);
            setPage(1);
          }}
          availableSectors={availableSectors}
        />

        {/* Screener Signals Table */}
        <ScreenerTable
          signals={signals}
          loading={loading}
          sortBy={sortBy}
          order={order}
          onSortChange={handleSortChange}
          onOpenChart={(t) => setChartTicker(t)}
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
            onPageChange={(p) => setPage(p)}
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
      />
    </div>
  );
};

export default App;
