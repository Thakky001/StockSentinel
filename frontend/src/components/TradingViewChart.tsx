/**
 * TradingViewChart – Candlestick + Volume + 30w SMA chart with Stan Weinstein 3 price lines.
 * Uses TradingView Lightweight Charts v4.
 */

import React, { useEffect, useRef } from 'react';
import {
  createChart,
  ColorType,
  LineStyle,
  IChartApi,
} from 'lightweight-charts';
import type { ChartData } from '../types/index.ts';

interface TradingViewChartProps {
  data: ChartData;
  height?: number;
}

const TradingViewChart: React.FC<TradingViewChartProps> = ({
  data,
  height = 450,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  if (!data || !data.candlesticks || data.candlesticks.length === 0) {
    return (
      <div className="h-[450px] flex flex-col items-center justify-center bg-slate-950/60 rounded-xl border border-amber-500/30 p-8 text-center space-y-3">
        <div className="w-14 h-14 rounded-full bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mx-auto text-2xl">
          📊
        </div>
        <h3 className="text-lg font-semibold text-slate-200">ไม่พบประวัติราคา กรุณาซิงก์ข้อมูล</h3>
        <p className="text-xs sm:text-sm text-slate-400 max-w-md">
          ไม่มีข้อมูลแท่งเทียนราคาจริงในฐานข้อมูล กรุณาซิงก์ข้อมูลแท่งราคาก่อนเปิดดูกราฟ
        </p>
      </div>
    );
  }

  useEffect(() => {
    if (!containerRef.current) return;

    // Deduplicate and ensure strictly ascending chronological ordering
    const sortedCandles = [...data.candlesticks]
      .sort((a, b) => a.time.localeCompare(b.time))
      .filter((c, idx, arr) => idx === 0 || c.time > arr[idx - 1].time);

    const sortedSma = [...data.sma30]
      .sort((a, b) => a.time.localeCompare(b.time))
      .filter((s, idx, arr) => idx === 0 || s.time > arr[idx - 1].time);

    const sortedVolume = [...data.volume]
      .sort((a, b) => a.time.localeCompare(b.time))
      .filter((v, idx, arr) => idx === 0 || v.time > arr[idx - 1].time);

    // Create Lightweight Chart instance
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: '#0f172a' }, // Slate 900
        textColor: '#94a3b8', // Slate 400
        fontSize: 12,
      },
      grid: {
        vertLines: { color: 'rgba(51, 65, 85, 0.4)' }, // Slate 700
        horzLines: { color: 'rgba(51, 65, 85, 0.4)' },
      },
      crosshair: {
        vertLine: { color: '#64748b', width: 1, style: LineStyle.Dashed },
        horzLine: { color: '#64748b', width: 1, style: LineStyle.Dashed },
      },
      timeScale: {
        borderColor: 'rgba(51, 65, 85, 0.8)',
        timeVisible: false,
      },
      rightPriceScale: {
        borderColor: 'rgba(51, 65, 85, 0.8)',
        scaleMargins: {
          top: 0.1,
          bottom: 0.25, // Leave bottom 25% for volume
        },
      },
    });
    chartRef.current = chart;

    // 1. Candlestick series
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });
    candleSeries.setData(sortedCandles as any);

    // 2. 30-week SMA line series
    if (sortedSma.length > 0) {
      const smaSeries = chart.addLineSeries({
        color: '#3b82f6', // Blue 500
        lineWidth: 2,
        title: '30w SMA',
        priceLineVisible: false,
      });
      smaSeries.setData(sortedSma as any);
    }

    // 3. Volume histogram (overlay confined to bottom 20%)
    if (sortedVolume.length > 0) {
      const volumeSeries = chart.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceScaleId: '', // Overlay series without price axis conflict
      });
      volumeSeries.priceScale().applyOptions({
        scaleMargins: {
          top: 0.8, // Confine volume histogram to bottom 20%
          bottom: 0,
        },
      });
      volumeSeries.setData(sortedVolume as any);
    }

    // 4. Weinstein Key Price Lines
    const { metrics } = data;
    if (metrics) {
      // Green line: Entry Pivot
      if (metrics.entry_price > 0) {
        candleSeries.createPriceLine({
          price: metrics.entry_price,
          color: '#22c55e',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `จุดเข้า: $${metrics.entry_price.toFixed(2)}`,
        });
      }

      // Amber/Orange line: Max Buy (+5%)
      if (metrics.max_buy_price > 0) {
        candleSeries.createPriceLine({
          price: metrics.max_buy_price,
          color: '#f59e0b',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `เพดานซื้อ (+5%): $${metrics.max_buy_price.toFixed(2)}`,
        });
      }

      // Red line: Stop Loss (-8%)
      if (metrics.stop_loss_price > 0) {
        candleSeries.createPriceLine({
          price: metrics.stop_loss_price,
          color: '#ef4444',
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title: `Stop Loss: $${metrics.stop_loss_price.toFixed(2)}`,
        });
      }
    }

    // Responsive Auto-resize via ResizeObserver
    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
        });
      }
    };
    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(containerRef.current);

    // Fit content into viewport
    chart.timeScale().fitContent();

    return () => {
      resizeObserver.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [data, height]);

  return (
    <div className="relative w-full rounded-lg overflow-hidden border border-slate-700/80">
      <div ref={containerRef} className="w-full" style={{ height }} />
      {/* Legend overlay */}
      <div className="absolute top-2 left-3 flex flex-wrap items-center gap-3 text-xs bg-slate-900/80 backdrop-blur px-2.5 py-1 rounded border border-slate-700/60 pointer-events-none">
        <span className="flex items-center gap-1 text-blue-400 font-medium">
          <span className="w-2.5 h-0.5 bg-blue-500 inline-block" /> 30w SMA
        </span>
        <span className="flex items-center gap-1 text-emerald-400 font-medium">
          <span className="w-2.5 h-0.5 bg-emerald-500 inline-block border-b border-dashed" /> จุดเข้าซื้อ (Pivot)
        </span>
        <span className="flex items-center gap-1 text-amber-400 font-medium">
          <span className="w-2.5 h-0.5 bg-amber-500 inline-block border-b border-dashed" /> เพดานซื้อ (+5%)
        </span>
        <span className="flex items-center gap-1 text-rose-400 font-medium">
          <span className="w-2.5 h-0.5 bg-rose-500 inline-block border-b border-dashed" /> จุด Stop Loss
        </span>
      </div>
    </div>
  );
};

export default TradingViewChart;
