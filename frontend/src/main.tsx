import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './index.css'

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, ErrorBoundaryState> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[StockSentinel] Uncaught error caught by ErrorBoundary:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-slate-900 text-slate-100 flex flex-col items-center justify-center p-6 text-center">
          <div className="bg-slate-800 border border-rose-500/40 rounded-2xl p-8 max-w-lg shadow-2xl">
            <span className="text-4xl mb-4 block">⚠️</span>
            <h1 className="text-xl font-bold text-rose-400 mb-2">เกิดข้อผิดพลาดในการโหลดหน้าเว็บ</h1>
            <p className="text-xs text-slate-300 font-mono bg-slate-950 p-3 rounded-lg mb-4 text-left overflow-x-auto whitespace-pre-wrap">
              {this.state.error?.message || String(this.state.error)}
            </p>
            <button
              onClick={() => {
                try {
                  localStorage.clear();
                } catch {}
                window.location.reload();
              }}
              className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-semibold px-5 py-2.5 rounded-lg transition-colors focus:outline-none"
            >
              รีเฟรชหน้าเว็บ (Clear Cache & Reload)
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * StockSentinel React 18 application entry point.
 * Uses createRoot for concurrent mode rendering.
 */
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
