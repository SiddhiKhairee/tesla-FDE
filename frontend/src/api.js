// Thin client for the FastAPI backend. Dev requests go through the Vite
// proxy configured in vite.config.js, so relative paths work without CORS
// setup on the backend.

export async function fetchTickets() {
  const response = await fetch('/tickets')
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
  const response = await fetch('/reports/intake', {
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
