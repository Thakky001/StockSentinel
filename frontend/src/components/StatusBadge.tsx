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
  ScreenerSignal['status'],
  { label: string; className: string }
> = {
  IN_BUY_ZONE: {
    label: 'อยู่ในโซนซื้อ',
    className:
      'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
  },
  EXTENDED: {
    label: 'พุ่งเกินโซน (+5%)',
    className:
      'bg-amber-500/15 text-amber-400 border border-amber-500/30',
  },
  BELOW_ENTRY: {
    label: 'ยังไม่ถึงจุดเข้า',
    className:
      'bg-blue-500/15 text-blue-400 border border-blue-500/30',
  },
  STOPPED_OUT: {
    label: 'หลุด Stop Loss',
    className:
      'bg-rose-500/15 text-rose-400 border border-rose-500/30',
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
