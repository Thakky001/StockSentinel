/**
 * ScreenerTable – Responsive, sortable data table for Stan Weinstein Stage 2 breakouts.
 */

import React from 'react';
import type { ScreenerSignal } from '../types/index.ts';
import StatusBadge from './StatusBadge.tsx';

interface ScreenerTableProps {
  signals: ScreenerSignal[];
  loading: boolean;
  sortBy: string;
  order: 'asc' | 'desc';
  portfolioSize?: number;
  riskPct?: number;
  onSortChange: (column: string) => void;
  onOpenChart: (ticker: string) => void;
  onOpenCalculator?: (entry: number, stop: number) => void;
  isWatchlisted: (ticker: string) => boolean;
  onToggleWatchlist: (signal: ScreenerSignal) => void;
}

interface ColumnDef {
  key: string;
  label: string;
  align?: 'left' | 'right' | 'center';
  sortable?: boolean;
}

const COLUMNS: ColumnDef[] = [
  { key: 'watchlist', label: '⭐', align: 'center', sortable: false },
  { key: 'ticker', label: 'หุ้น / ชื่อบริษัท', align: 'left', sortable: true },
  { key: 'quality_score', label: 'คุณภาพ (Score)', align: 'center', sortable: true },
  { key: 'sector', label: 'กลุ่มอุตสาหกรรม', align: 'left', sortable: false },
  { key: 'close_price', label: 'ราคาปิด', align: 'right', sortable: true },
  { key: 'entry_price', label: 'จุดเข้าซื้อ (Pivot)', align: 'right', sortable: true },
  { key: 'max_buy_price', label: 'เพดานซื้อ (+5%)', align: 'right', sortable: false },
  { key: 'stop_loss_price', label: 'Stop Loss', align: 'right', sortable: false },
  { key: 'base_tightness_pct', label: 'กรอบฐาน 4w', align: 'right', sortable: true },
  { key: 'atr_14w', label: 'ATR (14w)', align: 'right', sortable: true },
  { key: 'recommended_shares', label: 'ไม้ซื้อ (หุ้น)', align: 'right', sortable: false },
  { key: 'diff_pct', label: 'เทียบจุดเข้า %', align: 'right', sortable: true },
  { key: 'status', label: 'สถานะโซนซื้อ', align: 'center', sortable: true },
  { key: 'volume_surge_ratio', label: 'โวลุ่มเข้า (เท่า)', align: 'right', sortable: true },
  { key: 'mrs_score', label: 'Mansfield RS', align: 'right', sortable: true },
  { key: 'sma_30w_slope', label: 'ความชัน 30w', align: 'right', sortable: true },
  { key: 'actions', label: 'เครื่องมือ', align: 'center', sortable: false },
];

const ScreenerTable: React.FC<ScreenerTableProps> = ({
  signals,
  loading,
  sortBy,
  order,
  portfolioSize = 10000,
  riskPct = 1.0,
  onSortChange,
  onOpenChart,
  onOpenCalculator,
  isWatchlisted,
  onToggleWatchlist,
}) => {
  if (loading) {
    return (
      <div className="bg-slate-800/80 border border-slate-700/80 rounded-xl p-12 text-center shadow-sm">
        <div className="inline-block animate-spin h-8 w-8 border-4 border-blue-500 border-t-transparent rounded-full mb-3" />
        <p className="text-slate-400 text-sm">กำลังโหลดข้อมูลสัญญาณหุ้น Stage 2...</p>
      </div>
    );
  }

  if (signals.length === 0) {
    return (
      <div className="bg-slate-800/80 border border-slate-700/80 rounded-xl p-12 text-center shadow-sm">
        <span className="text-4xl mb-3 block">🔍</span>
        <h3 className="text-slate-200 font-semibold text-lg mb-1">ไม่พบหุ้นที่ผ่านเกณฑ์</h3>
        <p className="text-slate-400 text-sm max-w-md mx-auto">
          ไม่พบหุ้นที่เข้าเงื่อนไข Weinstein Stage 2 Breakout ครบทุกข้อสำหรับรอบวันที่นี้และตัวกรองที่เลือก
        </p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/80 border border-slate-700/80 rounded-xl shadow-sm overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse text-sm">
          <thead>
            <tr className="bg-slate-900/80 border-b border-slate-700 text-slate-400 text-xs uppercase tracking-wider font-semibold">
              {COLUMNS.map((col) => {
                const isCurrentSort = sortBy === col.key;
                return (
                  <th
                    key={col.key}
                    scope="col"
                    className={`py-3 px-4 select-none ${
                      col.align === 'right'
                        ? 'text-right'
                        : col.align === 'center'
                        ? 'text-center'
                        : 'text-left'
                    } ${col.sortable ? 'cursor-pointer hover:text-slate-200 transition-colors' : ''}`}
                    onClick={() => col.sortable && onSortChange(col.key)}
                  >
                    <div
                      className={`inline-flex items-center gap-1 ${
                        col.align === 'right'
                          ? 'justify-end'
                          : col.align === 'center'
                          ? 'justify-center'
                          : 'justify-start'
                      }`}
                    >
                      <span>{col.label}</span>
                      {col.sortable && isCurrentSort && (
                        <span className="text-blue-400 text-xs font-bold">
                          {order === 'asc' ? '▲' : '▼'}
                        </span>
                      )}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {signals.map((sig) => {
              const watch = isWatchlisted(sig.ticker);
              const closePrice = Number(sig.close_price ?? sig.current_price ?? (sig as any).weekly_close ?? 0);
              const entryPrice = Number(sig.entry_price ?? 0);
              const maxBuyPrice = Number(sig.max_buy_price ?? 0);
              const stopLossPrice = Number(sig.stop_loss_price ?? 0);
              const diffPct = Number(sig.diff_pct ?? 0);
              const diffPositive = diffPct >= 0;
              const mrsScore = Number(sig.mrs_score ?? 0);
              const mrsPositive = mrsScore > 0;
              const slope = Number(sig.sma_30w_slope ?? 0);
              const slopePositive = slope >= 0;
              const volSurge = Number(sig.volume_surge_ratio ?? 0);
              const statusVal = sig.status ?? (sig as any).entry_status ?? 'IN_BUY_ZONE';

              return (
                <tr
                  key={sig.ticker}
                  className="hover:bg-slate-750 transition-colors group text-slate-200"
                >
                  {/* Watchlist toggle */}
                  <td className="py-3 px-4 text-center">
                    <button
                      onClick={() => onToggleWatchlist(sig)}
                      title={watch ? 'ลบออกจาก Watchlist' : 'เพิ่มใน Watchlist'}
                      className="text-lg leading-none hover:scale-125 transition-transform focus:outline-none"
                    >
                      {watch ? '⭐' : '☆'}
                    </button>
                  </td>

                  {/* Ticker & Name */}
                  <td className="py-3 px-4">
                    <div className="font-bold text-slate-100 flex items-center gap-1.5 flex-wrap">
                      <span>{sig.ticker}</span>
                      {sig.earnings_warning && (
                        <span
                          className="px-1.5 py-0.5 text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30 rounded font-semibold whitespace-nowrap animate-pulse"
                          title="วันประกาศผลการดำเนินงานใกล้ถึง"
                        >
                          {sig.earnings_warning}
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-400 truncate max-w-[180px]" title={sig.name}>
                      {sig.name}
                    </div>
                  </td>

                  {/* Quality Score & Grade Badge */}
                  <td className="py-3 px-4 text-center">
                    {(() => {
                      const score = Math.round(Number(sig.quality_score ?? 0));
                      const grade = sig.quality_grade || (score >= 90 ? 'A+' : score >= 80 ? 'A' : score >= 65 ? 'B' : 'C');
                      let badgeStyle = 'bg-slate-700/50 text-slate-400 border border-slate-600/50';
                      let icon = '⚪';
                      if (grade === 'A+') {
                        badgeStyle = 'bg-purple-500/20 text-purple-300 border border-purple-500/40 font-bold shadow-sm shadow-purple-500/20';
                        icon = '💎';
                      } else if (grade === 'A') {
                        badgeStyle = 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 font-semibold';
                        icon = '🟢';
                      } else if (grade === 'B') {
                        badgeStyle = 'bg-amber-500/20 text-amber-300 border border-amber-500/40 font-medium';
                        icon = '🟡';
                      }
                      return (
                        <div className="inline-flex items-center justify-center">
                          <span
                            className={`px-2 py-0.5 rounded-full text-xs whitespace-nowrap inline-flex items-center gap-1 font-mono ${badgeStyle}`}
                            title={`คะแนนคุณภาพ Breakout: ${score}/100 (เกรด ${grade})`}
                          >
                            <span>{icon}</span>
                            <span>{score}</span>
                            <span className="font-sans font-bold">{grade}</span>
                          </span>
                        </div>
                      );
                    })()}
                  </td>

                  {/* Sector */}
                  <td className="py-3 px-4 text-xs text-slate-400">
                    <span className="truncate block max-w-[120px]" title={sig.sector}>
                      {sig.sector || '—'}
                    </span>
                  </td>

                  {/* Weekly Close */}
                  <td className="py-3 px-4 text-right font-mono font-medium text-slate-100">
                    ${closePrice.toFixed(2)}
                  </td>

                  {/* Entry Price */}
                  <td className="py-3 px-4 text-right font-mono text-emerald-400 font-medium">
                    ${entryPrice.toFixed(2)}
                  </td>

                  {/* Max Buy */}
                  <td className="py-3 px-4 text-right font-mono text-amber-400/90 text-xs">
                    ${maxBuyPrice.toFixed(2)}
                  </td>

                  {/* Stop Loss */}
                  <td className="py-3 px-4 text-right font-mono text-xs">
                    <span className="text-rose-400/90 font-medium">${stopLossPrice.toFixed(2)}</span>
                    {stopLossPrice >= entryPrice && entryPrice > 0 && (
                      <span className="block text-[10px] text-emerald-400 font-semibold" title="ยก Stop Loss ขึ้นมาจุดคุ้มทุน (Breakeven)">
                        🛡️ บังทุน
                      </span>
                    )}
                  </td>

                  {/* Base Tightness % (4w) */}
                  <td className="py-3 px-4 text-right font-mono text-xs">
                    {sig.base_tightness_pct != null ? (
                      <span
                        className={
                          Number(sig.base_tightness_pct) <= 18
                            ? 'text-emerald-400 font-semibold'
                            : Number(sig.base_tightness_pct) <= 20
                            ? 'text-amber-400 font-medium'
                            : 'text-slate-400'
                        }
                        title={`กรอบบีบตัว 4 สัปดาห์: ${Number(sig.base_tightness_pct).toFixed(2)}%`}
                      >
                        {Number(sig.base_tightness_pct).toFixed(1)}%
                      </span>
                    ) : (
                      <span className="text-slate-500">—</span>
                    )}
                  </td>

                  {/* ATR (14w) */}
                  <td className="py-3 px-4 text-right font-mono text-xs text-slate-300">
                    {sig.atr_14w != null ? `$${Number(sig.atr_14w).toFixed(2)}` : '—'}
                  </td>

                  {/* Recommended Shares (Position Sizing) */}
                  <td className="py-3 px-4 text-right font-mono text-xs">
                    {(() => {
                      const riskAmount = (portfolioSize * riskPct) / 100;
                      const riskPerShare = Math.max(0.01, entryPrice - stopLossPrice);
                      const shares = Math.max(0, Math.floor(riskAmount / riskPerShare));
                      const capital = shares * closePrice;
                      return (
                        <div>
                          <span className="font-bold text-sky-400">
                            {shares.toLocaleString()} <span className="text-[10px] text-slate-400 font-normal">หุ้น</span>
                          </span>
                          <div className="text-[10px] text-slate-400/80">
                            ${capital.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                          </div>
                        </div>
                      );
                    })()}
                  </td>

                  {/* Distance % */}
                  <td className={`py-3 px-4 text-right font-mono text-xs ${
                    diffPositive ? 'text-emerald-400' : 'text-rose-400'
                  }`}>
                    <span className="font-semibold">{diffPositive ? '+' : ''}{diffPct.toFixed(2)}%</span>
                    {sig.peak_gain_pct != null && Number(sig.peak_gain_pct) > diffPct && (
                      <span className="block text-[10px] text-slate-400 font-normal" title="กำไรสูงสุดที่เคยทำได้นับตั้งแต่เบรกเอาต์">
                        Peak: +{Number(sig.peak_gain_pct).toFixed(1)}%
                      </span>
                    )}
                  </td>

                  {/* Status Badge */}
                  <td className="py-3 px-4 text-center">
                    <StatusBadge status={statusVal} />
                  </td>

                  {/* Volume Surge */}
                  <td className="py-3 px-4 text-right font-mono text-xs">
                    <span className={volSurge >= 1.5 ? 'font-bold text-emerald-400' : 'text-slate-400'}>
                      {volSurge.toFixed(1)}x
                    </span>
                  </td>

                  {/* Mansfield RS */}
                  <td className={`py-3 px-4 text-right font-mono text-xs font-semibold ${
                    mrsPositive ? 'text-emerald-400' : 'text-rose-400'
                  }`}>
                    {mrsPositive ? '+' : ''}{mrsScore.toFixed(1)}
                  </td>

                  {/* 30w SMA Slope */}
                  <td className={`py-3 px-4 text-right font-mono text-xs ${
                    slopePositive ? 'text-emerald-400' : 'text-rose-400'
                  }`}>
                    {slopePositive ? '+' : ''}{slope.toFixed(1)}%
                  </td>

                  {/* Actions buttons */}
                  <td className="py-3 px-4 text-center">
                    <div className="flex items-center justify-center gap-1.5">
                      <button
                        onClick={() => onOpenChart(sig.ticker)}
                        className="bg-blue-600/80 hover:bg-blue-600 text-white text-xs font-medium px-2.5 py-1 rounded-md transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 whitespace-nowrap"
                      >
                        ดูกราฟ
                      </button>
                      {onOpenCalculator && (
                        <button
                          onClick={() => onOpenCalculator(entryPrice, stopLossPrice)}
                          title="คำนวณไม้และคุมความเสี่ยง"
                          className="bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs px-2 py-1 rounded-md transition-colors"
                        >
                          🧮
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default ScreenerTable;
