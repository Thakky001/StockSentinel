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
  onSortChange: (column: string) => void;
  onOpenChart: (ticker: string) => void;
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
  { key: 'sector', label: 'กลุ่มอุตสาหกรรม', align: 'left', sortable: false },
  { key: 'close_price', label: 'ราคาปิด', align: 'right', sortable: true },
  { key: 'entry_price', label: 'จุดเข้าซื้อ (Pivot)', align: 'right', sortable: true },
  { key: 'max_buy_price', label: 'เพดานซื้อ (+5%)', align: 'right', sortable: false },
  { key: 'stop_loss_price', label: 'Stop Loss', align: 'right', sortable: false },
  { key: 'diff_pct', label: 'เทียบจุดเข้า %', align: 'right', sortable: true },
  { key: 'status', label: 'สถานะโซนซื้อ', align: 'center', sortable: true },
  { key: 'volume_surge_ratio', label: 'โวลุ่มเข้า (เท่า)', align: 'right', sortable: true },
  { key: 'mrs_score', label: 'Mansfield RS', align: 'right', sortable: true },
  { key: 'sma_30w_slope', label: 'ความชัน 30w', align: 'right', sortable: true },
  { key: 'actions', label: 'ดูกราฟ', align: 'center', sortable: false },
];

const ScreenerTable: React.FC<ScreenerTableProps> = ({
  signals,
  loading,
  sortBy,
  order,
  onSortChange,
  onOpenChart,
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
              const diffPositive = sig.diff_pct >= 0;
              const mrsPositive = sig.mrs_score > 0;
              const slopePositive = sig.sma_30w_slope >= 0;

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
                    <div className="font-bold text-slate-100 flex items-center gap-1.5">
                      <span>{sig.ticker}</span>
                    </div>
                    <div className="text-xs text-slate-400 truncate max-w-[180px]" title={sig.name}>
                      {sig.name}
                    </div>
                  </td>

                  {/* Sector */}
                  <td className="py-3 px-4 text-xs text-slate-400">
                    <span className="truncate block max-w-[120px]" title={sig.sector}>
                      {sig.sector || '—'}
                    </span>
                  </td>

                  {/* Weekly Close */}
                  <td className="py-3 px-4 text-right font-mono font-medium text-slate-100">
                    ${Number(sig.close_price).toFixed(2)}
                  </td>

                  {/* Entry Price */}
                  <td className="py-3 px-4 text-right font-mono text-emerald-400 font-medium">
                    ${Number(sig.entry_price).toFixed(2)}
                  </td>

                  {/* Max Buy */}
                  <td className="py-3 px-4 text-right font-mono text-amber-400/90 text-xs">
                    ${Number(sig.max_buy_price).toFixed(2)}
                  </td>

                  {/* Stop Loss */}
                  <td className="py-3 px-4 text-right font-mono text-rose-400/90 text-xs">
                    ${Number(sig.stop_loss_price).toFixed(2)}
                  </td>

                  {/* Distance % */}
                  <td className={`py-3 px-4 text-right font-mono font-semibold text-xs ${
                    diffPositive ? 'text-emerald-400' : 'text-rose-400'
                  }`}>
                    {diffPositive ? '+' : ''}{Number(sig.diff_pct).toFixed(2)}%
                  </td>

                  {/* Status Badge */}
                  <td className="py-3 px-4 text-center">
                    <StatusBadge status={sig.status} />
                  </td>

                  {/* Volume Surge */}
                  <td className="py-3 px-4 text-right font-mono text-xs">
                    <span className={sig.volume_surge_ratio >= 1.5 ? 'font-bold text-emerald-400' : 'text-slate-400'}>
                      {Number(sig.volume_surge_ratio).toFixed(1)}x
                    </span>
                  </td>

                  {/* Mansfield RS */}
                  <td className={`py-3 px-4 text-right font-mono text-xs font-semibold ${
                    mrsPositive ? 'text-emerald-400' : 'text-rose-400'
                  }`}>
                    {mrsPositive ? '+' : ''}{Number(sig.mrs_score).toFixed(1)}
                  </td>

                  {/* 30w SMA Slope */}
                  <td className={`py-3 px-4 text-right font-mono text-xs ${
                    slopePositive ? 'text-emerald-400' : 'text-rose-400'
                  }`}>
                    {slopePositive ? '+' : ''}{Number(sig.sma_30w_slope).toFixed(1)}%
                  </td>

                  {/* Action button */}
                  <td className="py-3 px-4 text-center">
                    <button
                      onClick={() => onOpenChart(sig.ticker)}
                      className="bg-blue-600/80 hover:bg-blue-600 text-white text-xs font-medium px-2.5 py-1 rounded-md transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      ดูกราฟ
                    </button>
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
