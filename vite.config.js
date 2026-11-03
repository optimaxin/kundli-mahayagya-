import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// In development the API is proxied, so the browser (and phones on the LAN using `vite --host`)
// talk to the same origin and no CORS setup is needed. In production, serve the built site and
// the API under one domain (reverse proxy `/api` to the backend) or set VITE_API_BASE_URL.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        '/api': { target: env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
      },
    },
  }
})
