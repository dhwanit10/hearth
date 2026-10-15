import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Where the FastAPI backend lives during development. The dev server proxies
// both the REST API and the websocket upgrade, so the browser only ever talks
// to a single origin and no CORS/preflight dance is needed in the app code.
const API_TARGET = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
      "/ws": { target: API_TARGET, ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    target: "es2022",
  },
  test: {
    environment: "jsdom",
    include: ["test/**/*.test.{js,jsx}"],
  },
});
