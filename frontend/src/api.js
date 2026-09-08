// Thin client for the FastAPI backend. Local dev requests go through the
// Vite proxy configured in vite.config.js (relative paths, no CORS setup
// needed), which is why API_BASE defaults to '' — a deployed build (e.g.
// Vercel) has no such proxy, so VITE_API_BASE_URL there is set to the
// deployed backend's full URL (e.g. https://your-backend.onrender.com)
// and every call below becomes an absolute cross-origin request instead
// (see backend/main.py's ALLOWED_ORIGIN CORS config for the other half).
const API_BASE = import.meta.env.VITE_API_BASE_URL || ''

export async function fetchTickets() {
  const response = await fetch(`${API_BASE}/tickets`)
  if (!response.ok) {
    throw new Error(`GET /tickets failed: ${response.status} ${response.statusText}`)
  }
  return response.json()
}

// Hits the real diagnosis engine + Slack webhook — not instant, and prone
// to the same upstream LLM 503s seen elsewhere in this project. FastAPI
// returns a plain-text body (not JSON) for an unhandled 500, so parsing
// the error body is best-effort.
export async function submitReport(payload) {
  const response = await fetch(`${API_BASE}/reports/intake`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => null)
    const message = detail?.detail ? JSON.stringify(detail.detail) : response.statusText
    throw new Error(`POST /reports/intake failed: ${response.status} ${message}`)
  }
  return response.json()
}
