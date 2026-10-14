/**
 * Express application setup for StockSentinel backend.
 *
 * Configures:
 *   - JSON body parser
 *   - CORS (origins from CORS_ORIGIN env var, defaults to localhost:5173)
 *   - Route mounting: /api/screener, /api/stock, /api/notifications
 *   - 404 handler
 *   - Generic error handler middleware (returns ApiResponse<never> shape)
 */

import express, { Application, Request, Response, NextFunction } from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import path from 'path';
import fs from 'fs';

import screenerRouter from './routes/screener';
import stockRouter from './routes/stock';
import notificationsRouter from './routes/notifications';

// Load .env from the project root (one directory up from backend/)
dotenv.config({ path: '../.env' });

const app: Application = express();

// ---------------------------------------------------------------------------
// CORS
// ---------------------------------------------------------------------------
// Support comma-separated origins in CORS_ORIGIN for multi-environment setups
// e.g. CORS_ORIGIN=http://localhost:5173,https://app.example.com
const rawOrigins = process.env.CORS_ORIGIN ?? 'http://localhost:5173';
const allowedOrigins = rawOrigins
  .split(',')
  .map((o) => o.trim())
  .filter(Boolean);

app.use(
  cors({
    origin: (origin, callback) => {
      // Allow requests with no origin (e.g. curl, Postman, server-to-server)
      if (!origin) return callback(null, true);
      if (allowedOrigins.includes(origin)) return callback(null, true);
      callback(new Error(`CORS: Origin '${origin}' is not allowed.`));
    },
    methods: ['GET', 'POST', 'OPTIONS'],
    allowedHeaders: ['Content-Type', 'Authorization'],
    credentials: true,
  }),
);

// ---------------------------------------------------------------------------
// Body Parsers
// ---------------------------------------------------------------------------
app.use(express.json({ limit: '1mb' }));
app.use(express.urlencoded({ extended: false }));

// ---------------------------------------------------------------------------
// Health Check (unauthenticated, bypasses CORS for load-balancer probes)
// ---------------------------------------------------------------------------
app.get('/health', (_req: Request, res: Response) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// ---------------------------------------------------------------------------
// API Routes
// ---------------------------------------------------------------------------
app.use('/api/screener', screenerRouter);
app.use('/api/stock', stockRouter);
app.use('/api/notifications', notificationsRouter);

// ---------------------------------------------------------------------------
// Static Frontend Serving (Production / Docker / Render)
// ---------------------------------------------------------------------------
const frontendDist = path.resolve(__dirname, '../../frontend/dist');
if (fs.existsSync(frontendDist)) {
  app.use(express.static(frontendDist));
  app.get('*', (req: Request, res: Response, next: NextFunction) => {
    if (req.path.startsWith('/api') || req.path === '/health') return next();
    res.sendFile(path.join(frontendDist, 'index.html'));
  });
}

// ---------------------------------------------------------------------------
// 404 Handler — catches all unmatched routes
// ---------------------------------------------------------------------------
app.use((_req: Request, res: Response) => {
  res.status(404).json({
    success: false,
    error: {
      code: 'NOT_FOUND',
      message: 'The requested endpoint does not exist.',
    },
  });
});

// ---------------------------------------------------------------------------
// Global Error Handler
// ---------------------------------------------------------------------------
// Must have exactly 4 parameters so Express recognises it as an error handler
// eslint-disable-next-line @typescript-eslint/no-unused-vars
app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  // CORS policy violations (thrown by the CORS middleware callback)
  if (err instanceof Error && err.message.startsWith('CORS:')) {
    res.status(403).json({
      success: false,
      error: { code: 'CORS_FORBIDDEN', message: err.message },
    });
    return;
  }

  // Log unexpected errors server-side
  console.error('[ErrorHandler]', err);

  const message =
    err instanceof Error ? err.message : 'An unexpected internal server error occurred.';

  res.status(500).json({
    success: false,
    error: {
      code: 'INTERNAL_SERVER_ERROR',
      message,
    },
  });
});

export default app;
