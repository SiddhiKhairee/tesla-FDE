import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-only proxy to the FastAPI backend (uvicorn default, port 8000) so
    // the dashboard can call relative paths like `/tickets` without CORS
    // config on the backend.
    proxy: {
      '/tickets': 'http://localhost:8000',
      '/pipeline': 'http://localhost:8000',
      '/reports': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
})
