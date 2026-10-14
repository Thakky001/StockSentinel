# =============================================================================
# StockSentinel Full-Stack Dockerfile (Optimized for Render.com deployment)
# Multi-stage build: Frontend (React) + Backend (Node/Express) + Screener (Python)
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Build Frontend (React + Vite + Tailwind CSS)
# -----------------------------------------------------------------------------
FROM node:20-bookworm-slim AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2: Build Backend (Express + TypeScript)
# -----------------------------------------------------------------------------
FROM node:20-bookworm-slim AS backend-builder
WORKDIR /app/backend

COPY backend/package*.json ./
RUN npm ci

COPY backend/ ./
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 3: Production Runtime (Node.js 20 + Python 3.11 + Polars Engine)
# -----------------------------------------------------------------------------
FROM node:20-bookworm-slim AS runner

# Install Python 3, pip, venv, and PostgreSQL client library
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    libpq-dev \
    curl \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create and activate Python virtual environment
ENV VIRTUAL_ENV=/app/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install Python dependencies (polars, yfinance, pyarrow, psycopg2-binary, requests)
COPY screener/requirements.txt ./screener/requirements.txt
RUN pip install --no-cache-dir -r ./screener/requirements.txt

# Copy Python screener engine and universe datasets
COPY screener/ ./screener/
COPY db/ ./db/

# Setup Backend production environment
WORKDIR /app/backend
COPY backend/package*.json ./
RUN npm ci --omit=dev

# Copy compiled backend dist from Stage 2
COPY --from=backend-builder /app/backend/dist ./dist

# Copy compiled frontend dist from Stage 1 (served statically by Express)
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Render sets PORT dynamically (default 10000 on Render)
ENV PORT=10000
ENV NODE_ENV=production
EXPOSE 10000

# Health check probe for container orchestrator
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

# Start the Node.js Express server (serves /api and React frontend on /)
CMD ["node", "dist/index.js"]
