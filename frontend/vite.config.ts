import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served by FastAPI at /app once built; in dev, /api is proxied to uvicorn.
export default defineConfig({
  plugins: [react()],
  base: "/app/",
  server: {
    port: 5173,
    // Long timeouts: bulk AI enrichment of a large file can run for many minutes.
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true, timeout: 30 * 60 * 1000, proxyTimeout: 30 * 60 * 1000 } },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
