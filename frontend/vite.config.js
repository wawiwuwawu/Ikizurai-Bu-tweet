import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev proxy: /api → backend FastAPI (port 8097)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8097',
      '/healthz': 'http://127.0.0.1:8097',
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
