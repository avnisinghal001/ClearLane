import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Same-origin "/api" everywhere: in dev we proxy it to the local backend; on
// Vercel the platform routes "/api" to the Python function. Override the dev
// backend target with VITE_BACKEND_PROXY (defaults to localhost:8000).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_BACKEND_PROXY || "http://localhost:8000";
  return {
    plugins: [react()],
    resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
    server: {
      port: 5174,
      host: true,
      proxy: { "/api": { target: backend, changeOrigin: true } },
    },
    build: { outDir: "dist", chunkSizeWarningLimit: 1500 },
  };
});
