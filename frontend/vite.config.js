import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// Same-origin "/api" everywhere: in dev we proxy it to the local backend; on
// Vercel the platform routes "/api" to the Python serverless function. Override
// the dev backend target with VITE_BACKEND_PROXY (defaults to localhost:8000).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backend = env.VITE_BACKEND_PROXY || "http://localhost:8000";
  return {
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: "auto",
      // let the app be installed + work offline (police/citizens use it in the field)
      includeAssets: ["apple-touch-icon.png", "icon.svg", "icon-maskable.svg"],
      manifest: {
        name: "ClearLane — Parking Enforcement Intelligence",
        short_name: "ClearLane",
        description: "Bias-corrected parking-enforcement intelligence + live command for Bengaluru. Works offline.",
        id: "/",
        start_url: "/",
        scope: "/",
        display: "standalone",
        orientation: "portrait",
        background_color: "#070A10",
        theme_color: "#070A10",
        categories: ["navigation", "utilities", "government"],
        icons: [
          { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
          { src: "/icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
          { src: "/apple-touch-icon.png", sizes: "512x512", type: "image/png", purpose: "any" },
        ],
      },
      workbox: {
        // precache the app shell + the bundled demo JSON so it opens fully offline.
        // The big onboarding/login images are runtime-cached instead (keeps install lean).
        globPatterns: ["**/*.{js,css,html,svg,ico,json,webmanifest}"],
        globIgnores: ["**/img/*.png"],
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024,
        navigateFallback: "/index.html",
        cleanupOutdatedCaches: true,
        runtimeCaching: [
          {
            // onboarding / login imagery — cache after first view for offline use
            urlPattern: /\/img\/.*\.(png|jpg|webp)$/i,
            handler: "CacheFirst",
            options: {
              cacheName: "app-images",
              expiration: { maxEntries: 12, maxAgeSeconds: 60 * 60 * 24 * 30 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // map basemap tiles — cache so the map renders offline after first view
            urlPattern: /^https:\/\/[a-d]?\.?basemaps\.cartocdn\.com\/.*/i,
            handler: "CacheFirst",
            options: {
              cacheName: "map-tiles",
              expiration: { maxEntries: 500, maxAgeSeconds: 60 * 60 * 24 * 14 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // OpenStreetMap routing (trip planner) — fresh when online, fall back to cache
            urlPattern: /^https:\/\/router\.project-osrm\.org\/.*/i,
            handler: "NetworkFirst",
            options: {
              cacheName: "osrm-routes",
              expiration: { maxEntries: 60, maxAgeSeconds: 60 * 60 * 24 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
          {
            // live backend reads — network first, cached responses as offline fallback
            urlPattern: /\/api\/.*/i,
            handler: "NetworkFirst",
            options: {
              cacheName: "api",
              networkTimeoutSeconds: 4,
              expiration: { maxEntries: 120, maxAgeSeconds: 60 * 60 * 24 },
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      // keep the SW OFF during `npm run dev` (avoids stale-cache surprises while
      // editing). Test/installation works via `npm run preview` or production.
      devOptions: { enabled: false },
    }),
  ],
  server: {
    port: 5173,
    host: true,
    proxy: { "/api": { target: backend, changeOrigin: true } },
  },
  build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
  };
});
