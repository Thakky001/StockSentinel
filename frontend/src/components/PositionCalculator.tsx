/**
 * PositionCalculator – Real-time risk management and position sizing calculator
 * based on account size, maximum allowable trade risk %, entry price, and stop loss.
 */

import React, { useState, useEffect } from 'react';

interface PositionCalculatorProps {
  isOpen: boolean;
  onClose: () => void;
  initialEntryPrice?: number;
  initialStopLoss?: number;
  initialAccountSize?: number;
  initialRiskPct?: number;
}

const PositionCalculator: React.FC<PositionCalculatorProps> = ({
  isOpen,
  onClose,
  initialEntryPrice = 100,
  initialStopLoss = 92,
  initialAccountSize = 10000,
  initialRiskPct = 1.0,
}) => {
  const [accountSize, setAccountSize] = useState<number>(initialAccountSize);
  const [riskPct, setRiskPct] = useState<number>(initialRiskPct);
  const [entryPrice, setEntryPrice] = useState<number>(initialEntryPrice);
  const [stopLoss, setStopLoss] = useState<number>(initialStopLoss);

  useEffect(() => {
    if (initialEntryPrice > 0) setEntryPrice(initialEntryPrice);
    if (initialStopLoss > 0) setStopLoss(initialStopLoss);
    if (initialAccountSize > 0) setAccountSize(initialAccountSize);
    if (initialRiskPct > 0) setRiskPct(initialRiskPct);
  }, [initialEntryPrice, initialStopLoss, initialAccountSize, initialRiskPct]);

  // Close on Escape key press
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  // Mathematical computations
  const dollarRisk = (accountSize * riskPct) / 100;
  const riskPerShare = entryPrice - stopLoss;
  const riskPerSharePct = entryPrice > 0 ? (riskPerShare / entryPrice) * 100 : 0;
  
  const isValidRisk = riskPerShare > 0;
  const positionShares = isValidRisk ? Math.floor(dollarRisk / riskPerShare) : 0;
  const capitalRequired = positionShares * entryPrice;
  const portfolioAllocationPct = accountSize > 0 ? (capitalRequired / accountSize) * 100 : 0;
  const actualMaxDollarLoss = positionShares * riskPerShare;
  
  // 2R Target calculations
  const targetPrice2R = entryPrice + riskPerShare * 2;
  const targetGain2R = positionShares * (riskPerShare * 2);

  // Safety flags
  const isStopAboveEntry = stopLoss >= entryPrice;
  const isExceedingCapital = capitalRequired > accountSize;
  const isZeroShares = isValidRisk && positionShares <= 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-fadeIn">
      {/* Backdrop */}
      <div className="absolute inset-0" onClick={onClose} />

      {/* Modal Dialog */}
      <div className="relative w-full max-w-xl bg-slate-900 border border-slate-700/80 rounded-2xl shadow-2xl overflow-hidden z-10 flex flex-col">
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-slate-800 flex items-center justify-between bg-slate-900/90">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">🧮</span>
            <div>
              <h2 className="text-lg sm:text-xl font-bold text-slate-100">
                เครื่องคำนวณขนาดไม้ & บริหารความเสี่ยง
              </h2>
              <p className="text-xs text-slate-400">
                การคำนวณ Position Sizing และคุมความเสี่ยงตามหลัก Stan Weinstein
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-100 w-8 h-8 rounded-lg flex items-center justify-center text-lg hover:bg-slate-800 transition-colors"
          >
            ✕
          </button>
        </div>

        {/* Form & Results Body */}
        <div className="p-5 space-y-5 overflow-y-auto max-h-[85vh]">
          {/* Inputs Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Account Size */}
            <div>
              <label className="text-xs text-slate-300 font-medium block mb-1">
                มูลค่าพอร์ตลงทุน ($)
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400 text-sm">
                  $
                </span>
                <input
                  type="number"
                  min="1000"
                  step="1000"
                  value={accountSize}
                  onChange={(e) => setAccountSize(Math.max(0, parseFloat(e.target.value) || 0))}
                  className="w-full bg-slate-800 border border-slate-700 text-slate-100 text-sm rounded-lg pl-7 pr-3 py-2 font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            {/* Risk Per Trade % */}
            <div>
              <label className="text-xs text-slate-300 font-medium block mb-1">
                ความเสี่ยงสูงสุดต่อไม้ (%)
              </label>
              <div className="relative">
                <input
                  type="number"
                  min="0.1"
                  max="10.0"
                  step="0.25"
                  value={riskPct}
                  onChange={(e) => setRiskPct(Math.max(0, parseFloat(e.target.value) || 0))}
                  className="w-full bg-slate-800 border border-slate-700 text-slate-100 text-sm rounded-lg px-3 py-2 font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <span className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400 text-sm">
                  %
                </span>
              </div>
            </div>

            {/* Entry Price */}
            <div>
              <label className="text-xs text-slate-300 font-medium block mb-1">
                ราคาเข้าซื้อที่วางแผน ($)
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400 text-sm">
                  $
                </span>
                <input
                  type="number"
                  min="0.01"
                  step="0.1"
                  value={entryPrice}
                  onChange={(e) => setEntryPrice(Math.max(0, parseFloat(e.target.value) || 0))}
                  className="w-full bg-slate-800 border border-slate-700 text-slate-100 text-sm rounded-lg pl-7 pr-3 py-2 font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>

            {/* Stop Loss Price */}
            <div>
              <label className="text-xs text-slate-300 font-medium block mb-1">
                ราคาตัดขาดทุน Stop Loss ($)
              </label>
              <div className="relative">
                <span className="absolute inset-y-0 left-0 pl-3 flex items-center text-slate-400 text-sm">
                  $
                </span>
                <input
                  type="number"
                  min="0.01"
                  step="0.1"
                  value={stopLoss}
                  onChange={(e) => setStopLoss(Math.max(0, parseFloat(e.target.value) || 0))}
                  className="w-full bg-slate-800 border border-slate-700 text-slate-100 text-sm rounded-lg pl-7 pr-3 py-2 font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
          </div>

          {/* Validation Warnings */}
          {isStopAboveEntry && (
            <div className="bg-rose-950/60 border border-rose-800 text-rose-300 text-xs rounded-lg p-3 flex items-center gap-2">
              <span>⚠️</span>
              <span>ราคาตัดขาดทุน (Stop Loss) ต้องต่ำกว่าราคาที่วางแผนจะเข้าซื้อ</span>
            </div>
          )}

          {isExceedingCapital && (
            <div className="bg-amber-950/60 border border-amber-800 text-amber-300 text-xs rounded-lg p-3 flex items-center gap-2">
              <span>⚠️</span>
              <span>
                เงินลงทุนที่ต้องใช้ (${capitalRequired.toLocaleString()}) เกินขนาดพอร์ตของคุณ! ต้องใช้มาร์จิ้นหรือปรับลด % ความเสี่ยงลง
              </span>
            </div>
          )}

          {isZeroShares && (
            <div className="bg-blue-950/60 border border-blue-800 text-blue-300 text-xs rounded-lg p-3 flex items-center gap-2">
              <span>ℹ️</span>
              <span>จำนวนเงินความเสี่ยงน้อยเกินไปสำหรับการซื้อหุ้นอย่างน้อย 1 หุ้น</span>
            </div>
          )}

          {/* Key Outputs Card */}
          <div className="bg-slate-800/80 border border-slate-700 rounded-xl p-4 space-y-3">
            <h3 className="text-xs uppercase tracking-wider text-slate-400 font-bold border-b border-slate-700/60 pb-2">
              ผลลัพธ์การคำนวณขนาดไม้และการคุมความเสี่ยง
            </h3>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 font-mono">
              <div className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-700/40">
                <span className="text-[11px] text-slate-400 block mb-0.5">จำนวนหุ้นที่ควรซื้อ</span>
                <span className="text-lg font-bold text-blue-400">
                  {positionShares.toLocaleString()} <span className="text-xs font-normal text-slate-400">หุ้น</span>
                </span>
              </div>

              <div className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-700/40">
                <span className="text-[11px] text-slate-400 block mb-0.5">เงินลงทุนที่ต้องใช้</span>
                <span className="text-lg font-bold text-slate-100">
                  ${capitalRequired.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </span>
              </div>

              <div className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-700/40">
                <span className="text-[11px] text-slate-400 block mb-0.5">ความเสี่ยงขาดทุนสูงสุด</span>
                <span className="text-lg font-bold text-rose-400">
                  ${actualMaxDollarLoss.toFixed(2)}
                </span>
              </div>

              <div className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-700/40">
                <span className="text-[11px] text-slate-400 block mb-0.5">ความเสี่ยงต่อหุ้น</span>
                <span className="text-sm font-semibold text-slate-200">
                  ${riskPerShare > 0 ? riskPerShare.toFixed(2) : '0.00'} ({riskPerSharePct.toFixed(1)}%)
                </span>
              </div>

              <div className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-700/40">
                <span className="text-[11px] text-slate-400 block mb-0.5">สัดส่วนในพอร์ต</span>
                <span className={`text-sm font-semibold ${portfolioAllocationPct > 100 ? 'text-amber-400' : 'text-slate-200'}`}>
                  {portfolioAllocationPct.toFixed(1)}%
                </span>
              </div>

              <div className="bg-slate-900/60 p-2.5 rounded-lg border border-slate-700/40">
                <span className="text-[11px] text-slate-400 block mb-0.5">เป้าหมายกำไร 2R</span>
                <span className="text-sm font-bold text-emerald-400">
                  ${targetPrice2R.toFixed(2)} (+${targetGain2R.toFixed(2)})
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/90 flex justify-end">
          <button
            onClick={onClose}
            className="bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold px-4 py-2 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            ปิดหน้าต่าง
          </button>
        </div>
      </div>
    </div>
  );
};

export default PositionCalculator;
