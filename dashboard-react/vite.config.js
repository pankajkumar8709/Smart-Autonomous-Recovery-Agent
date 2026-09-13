import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy /api to the FastAPI sandbox so the browser talks to Vite (same origin)
// and there are no CORS surprises in dev.
// Sandbox port follows config.py's SANDBOX_PORT env override (default 8000).
const sandboxPort = process.env.SANDBOX_PORT || "8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${sandboxPort}`,
        changeOrigin: true,
      },
    },
  },
});
