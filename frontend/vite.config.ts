import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The SPA talks to the backend through same-origin /api paths; the dev
    // server proxies them (HTTP and WebSocket) to the FastAPI app (M8/M10).
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        ws: true,
      },
    },
  },
})
