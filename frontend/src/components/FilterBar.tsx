/**
 * FilterBar - Search input, Sector dropdown, and Status badge tabs for the screener dashboard.
 */

import React, { useState, useEffect } from 'react';

interface FilterBarProps {
  search: string;
  onSearchChange: (search: string) => void;
  sector: string;
  onSectorChange: (sector: string) => void;
  status: string;
  onStatusChange: (status: string) => void;
  availableSectors: string[];
}

const STATUS_TABS = [
  { id: '', label: 'ทุกสถานะ' },
  { id: 'IN_BUY_ZONE', label: '🟢 ในโซนซื้อ', badgeColor: 'text-emerald-400' },
  { id: 'EXTENDED', label: '🟡 เกินโซน (+5%)', badgeColor: 'text-amber-400' },
  { id: 'BELOW_ENTRY', label: '⚪ ยังไม่ถึงจุดเข้า', badgeColor: 'text-blue-400' },
  { id: 'STOPPED_OUT', label: '🔴 หลุด Stop Loss', badgeColor: 'text-rose-400' },
];

const FilterBar: React.FC<FilterBarProps> = ({
  search,
  onSearchChange,
  sector,
  onSectorChange,
  status,
  onStatusChange,
  availableSectors,
}) => {
  const [localSearch, setLocalSearch] = useState(search);

  // Debounce search input by 300ms
  useEffect(() => {
    const handler = setTimeout(() => {
      onSearchChange(localSearch);
    }, 300);
    return () => clearTimeout(handler);
  }, [localSearch, onSearchChange]);

  // Sync external search updates back to localSearch
  useEffect(() => {
    setLocalSearch(search);
  }, [search]);

  return (
    <div className="bg-slate-800/80 border border-slate-700/80 rounded-xl p-4 mb-6 shadow-sm flex flex-col gap-4">
      {/* Top row: Search input and Sector dropdown */}
      <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
        {/* Search Input */}
        <div className="relative flex-1 max-w-md">
          <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400 text-sm">
            🔍
          </span>
          <input
            type="text"
            placeholder="ค้นหาชื่อย่อหุ้น หรือชื่อบริษัท..."
            value={localSearch}
            onChange={(e) => setLocalSearch(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 text-slate-100 text-sm rounded-lg pl-9 pr-3 py-2 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
          />
          {localSearch && (
            <button
              onClick={() => setLocalSearch('')}
              className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 hover:text-slate-200 text-xs"
            >
              ✕
            </button>
          )}
        </div>

        {/* Sector dropdown */}
        <div className="flex items-center gap-2">
          <label htmlFor="sector-filter" className="text-xs text-slate-400 font-medium whitespace-nowrap">
            กลุ่มอุตสาหกรรม:
          </label>
          <select
            id="sector-filter"
            value={sector}
            onChange={(e) => onSectorChange(e.target.value)}
            className="bg-slate-900 border border-slate-700 text-slate-100 text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent min-w-[160px]"
          >
            <option value="">ทุกกลุ่มอุตสาหกรรม</option>
            {availableSectors.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Bottom row: Status tabs */}
      <div className="flex flex-wrap gap-2 border-t border-slate-700/60 pt-3">
        {STATUS_TABS.map((tab) => {
          const isActive = status === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onStatusChange(tab.id)}
              className={`text-xs sm:text-sm font-medium px-3 py-1.5 rounded-lg transition-all ${
                isActive
                  ? 'bg-blue-600 text-white shadow-sm ring-1 ring-blue-400'
                  : 'bg-slate-900/60 text-slate-400 hover:text-slate-200 hover:bg-slate-900 border border-slate-700/50'
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default FilterBar;
