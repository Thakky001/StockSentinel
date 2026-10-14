/**
 * WatchlistDrawer – Slide-over drawer persisting favorited tickers with quick chart access.
 */

import React, { useEffect } from 'react';
import type { WatchlistItem } from '../types/index.ts';
import StatusBadge from './StatusBadge.tsx';

interface WatchlistDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  watchlist: WatchlistItem[];
  onRemove: (ticker: string) => void;
  onClear: () => void;
  onViewChart: (ticker: string) => void;
}

const WatchlistDrawer: React.FC<WatchlistDrawerProps> = ({
  isOpen,
  onClose,
  watchlist,
  onRemove,
  onClear,
  onViewChart,
}) => {
  // Close on Escape key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      <div className="fixed inset-y-0 right-0 max-w-full flex pl-10">
        <div className="w-screen max-w-md bg-slate-900 border-l border-slate-700/80 shadow-2xl flex flex-col">
          {/* Header */}
          <div className="p-4 sm:p-5 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xl">⭐</span>
              <h2 className="text-lg font-bold text-slate-100">หุ้นที่บันทึกไว้ (Watchlist)</h2>
              <span className="bg-blue-500/20 text-blue-400 text-xs px-2 py-0.5 rounded-full font-mono">
                {watchlist.length}
              </span>
            </div>
            <button
              onClick={onClose}
              className="text-slate-400 hover:text-slate-100 w-8 h-8 rounded-lg flex items-center justify-center text-lg hover:bg-slate-800 transition-colors"
              title="ปิด"
            >
              ✕
            </button>
          </div>

          {/* List Content */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {watchlist.length === 0 ? (
              <div className="text-center py-16 text-slate-500">
                <span className="text-4xl mb-3 block">⭐</span>
                <p className="text-slate-300 font-medium mb-1">ยังไม่มีหุ้นในรายการบันทึก</p>
                <p className="text-xs text-slate-500">
                  คลิกที่เครื่องหมายดาว ⭐ ในตารางสแกนหุ้นเพื่อติดตามหุ้นไว้ที่นี่
                </p>
              </div>
            ) : (
              watchlist.map((item) => {
                const itemPrice = Number(item.current_price ?? (item as any).close_price ?? 0);
                const itemEntry = Number(item.entry_price ?? 0);
                const itemStatus = item.status ?? (item as any).entry_status ?? 'IN_BUY_ZONE';

                return (
                  <div
                    key={item.ticker}
                    className="bg-slate-800/90 border border-slate-700/70 hover:border-slate-600 rounded-xl p-3.5 transition-all shadow-sm flex flex-col gap-2"
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-bold font-mono text-slate-100 text-base">
                            {item.ticker}
                          </span>
                          <StatusBadge status={itemStatus} />
                        </div>
                        <p className="text-xs text-slate-400 truncate max-w-[200px]" title={item.name}>
                          {item.name}
                        </p>
                      </div>

                      <button
                        onClick={() => onRemove(item.ticker)}
                        className="text-slate-500 hover:text-rose-400 text-sm p-1 rounded hover:bg-slate-700/50 transition-colors"
                        title="ลบออก"
                      >
                        ✕
                      </button>
                    </div>

                    <div className="flex items-center justify-between text-xs pt-1 border-t border-slate-700/40">
                      <div className="flex gap-3 font-mono">
                        <span className="text-slate-400">
                          ราคา: <b className="text-slate-200">${itemPrice.toFixed(2)}</b>
                        </span>
                        <span className="text-slate-400">
                          จุดเข้า: <b className="text-emerald-400">${itemEntry.toFixed(2)}</b>
                        </span>
                      </div>

                    <button
                      onClick={() => {
                        onViewChart(item.ticker);
                        onClose();
                      }}
                      className="bg-blue-600/80 hover:bg-blue-600 text-white text-xs px-2.5 py-1 rounded transition-colors font-medium shadow-sm"
                    >
                      ดูกราฟ
                    </button>
                  </div>
                </div>
              );
            })
          )}
          </div>

          {/* Footer actions */}
          {watchlist.length > 0 && (
            <div className="p-4 border-t border-slate-800 bg-slate-900/90 flex justify-between items-center">
              <button
                onClick={onClear}
                className="text-xs text-rose-400 hover:text-rose-300 hover:underline"
              >
                ล้างทั้งหมด
              </button>
              <button
                onClick={onClose}
                className="bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium px-4 py-2 rounded-lg transition-colors border border-slate-700"
              >
                ปิด
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default WatchlistDrawer;
