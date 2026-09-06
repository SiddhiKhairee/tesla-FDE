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
