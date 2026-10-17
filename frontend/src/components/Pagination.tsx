/**
 * Pagination – Controls for navigating paginated screener signal results.
 */

import React from 'react';

interface PaginationProps {
  page: number;
  totalPages: number;
  total: number;
  limit: number;
  onPageChange: (newPage: number) => void;
}

const Pagination: React.FC<PaginationProps> = ({
  page,
  totalPages,
  total,
  limit,
  onPageChange,
}) => {
  if (total === 0) return null;

  const startItem = (page - 1) * limit + 1;
  const endItem = Math.min(page * limit, total);

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between gap-3 py-4 text-xs sm:text-sm text-slate-400">
      {/* Item summary */}
      <div>
        แสดงรายการที่ <span className="font-semibold text-slate-200">{startItem}</span> ถึง{' '}
        <span className="font-semibold text-slate-200">{endItem}</span> จากทั้งหมด{' '}
        <span className="font-semibold text-slate-200">{total}</span> รายการ
      </div>

      {/* Navigation Buttons */}
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => onPageChange(1)}
          disabled={page <= 1}
          className="px-2.5 py-1.5 rounded-md bg-slate-800 border border-slate-700 hover:bg-slate-700 disabled:opacity-40 disabled:pointer-events-none text-slate-200 transition-colors"
          title="หน้าแรก"
        >
          ««
        </button>

        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="px-3 py-1.5 rounded-md bg-slate-800 border border-slate-700 hover:bg-slate-700 disabled:opacity-40 disabled:pointer-events-none text-slate-200 transition-colors"
        >
          ก่อนหน้า
        </button>

        <span className="px-3 py-1.5 bg-slate-900 border border-slate-700 text-slate-200 rounded-md font-medium">
          หน้า {page} จาก {Math.max(totalPages, 1)}
        </span>

        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          className="px-3 py-1.5 rounded-md bg-slate-800 border border-slate-700 hover:bg-slate-700 disabled:opacity-40 disabled:pointer-events-none text-slate-200 transition-colors"
        >
          ถัดไป
        </button>

        <button
          type="button"
          onClick={() => onPageChange(totalPages)}
          disabled={page >= totalPages}
          className="px-2.5 py-1.5 rounded-md bg-slate-800 border border-slate-700 hover:bg-slate-700 disabled:opacity-40 disabled:pointer-events-none text-slate-200 transition-colors"
          title="หน้าสุดท้าย"
        >
          »»
        </button>
      </div>
    </div>
  );
};

export default Pagination;
