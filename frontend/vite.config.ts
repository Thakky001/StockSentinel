import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Vite configuration for StockSentinel frontend.
 * Dev server runs on port 5173 and proxies all /api/* requests
 * to the Express backend on port 3001 to avoid CORS issues in development.
 */
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
