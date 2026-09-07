import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Backend port defaults to uvicorn's convention (8000). Override per-
  // machine via VITE_BACKEND_PORT in frontend/.env.local (gitignored, see
  // .env.local.example) — needed on any machine where 8000 is already
  // taken by something else, without touching this committed default.
  const env = loadEnv(mode, process.cwd(), '')
  const backendTarget = `http://localhost:${env.VITE_BACKEND_PORT || '8000'}`

  return {
    plugins: [react()],
    server: {
      // Dev-only proxy to the FastAPI backend so the dashboard can call
      // relative paths like `/tickets` without CORS config on the backend.
      proxy: {
        '/tickets': backendTarget,
        '/pipeline': backendTarget,
        '/reports': backendTarget,
        '/health': backendTarget,
      },
    },
  }
})
