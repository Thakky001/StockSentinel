/**
 * Typed API client for StockSentinel.
 * All requests are proxied through Vite's dev server to the Express backend (port 3001).
 * In production, the API should be served at the same origin or configured via env var.
 */

const BASE_URL = '/api';

/**
 * Generic fetch wrapper that handles JSON parsing and error extraction.
 * The backend wraps all successful responses in `{ success: true, data: T }`.
 *
 * @param path - API path (e.g., '/screener/latest')
 * @param options - Optional fetch RequestInit options
 * @returns Parsed `data` field from the API response
 * @throws Error with backend error message on non-2xx status
 */
async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ error: { message: res.statusText } }));
    throw new Error(err.error?.message || `API Error: ${res.status} ${res.statusText}`);
  }

  const json = await res.json();
  return json.data as T;
}

export default apiFetch;
