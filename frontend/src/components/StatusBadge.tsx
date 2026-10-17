/**
 * StatusBadge – Color-coded pill badge representing a screener signal's entry status.
 *
 * Status color mapping:
 *  IN_BUY_ZONE  → emerald (green)
 *  EXTENDED     → amber (yellow-orange)
 *  BELOW_ENTRY  → blue
 *  STOPPED_OUT  → rose (red)
 */

import React from 'react';
import type { ScreenerSignal } from '../types/index.ts';

interface StatusBadgeProps {
  status: ScreenerSignal['status'];
  /** Optional override for compact display */
  compact?: boolean;
}

const STATUS_CONFIG: Record<
  string,
  { label: string; className: string }
> = {
  IN_BUY_ZONE: {
    label: '🟢 โซนซื้อได้เปรียบ',
    className:
      'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 font-semibold',
  },
  EXTENDED: {
    label: '🟡 วิ่งเกินโซนซื้อ (+5%)',
    className:
      'bg-amber-500/20 text-amber-300 border border-amber-500/40 font-semibold',
  },
  PROFIT_RUN: {
    label: '🔵 รันเทรนด์กำไร (+15%)',
    className:
      'bg-sky-500/20 text-sky-300 border border-sky-500/40 font-semibold',
  },
  TRAILING_WARNING: {
    label: '🟠 เตือนล็อกกำไร (หลุด 10w)',
    className:
      'bg-orange-500/20 text-orange-300 border border-orange-500/40 font-semibold',
  },
  BELOW_ENTRY: {
    label: '⚪ จ่อเบรกแนวต้าน',
    className:
      'bg-slate-500/20 text-slate-300 border border-slate-500/40 font-semibold',
  },
  STOPPED_OUT: {
    label: '🔴 หลุดจุดตัดขาดทุน',
    className:
      'bg-rose-500/20 text-rose-300 border border-rose-500/40 font-semibold',
  },
};

const StatusBadge: React.FC<StatusBadgeProps> = ({ status, compact = false }) => {
  const config = STATUS_CONFIG[status] ?? {
    label: status,
    className: 'bg-slate-500/15 text-slate-400 border border-slate-500/30',
  };

  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${config.className} ${compact ? 'text-[10px]' : ''}`}
    >
      {config.label}
    </span>
  );
};

export default StatusBadge;
