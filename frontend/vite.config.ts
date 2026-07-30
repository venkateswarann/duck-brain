import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend location is injected by scripts/run.sh so the launcher can move ports.
const backendHost = process.env.DCS_BACKEND_HOST || "127.0.0.1";
const backendPort = process.env.DCS_BACKEND_PORT || "8000";
const httpTarget = `http://${backendHost}:${backendPort}`;
const wsTarget = `ws://${backendHost}:${backendPort}`;

export default defineConfig({
  plugins: [react()],
  server: {
    port: Number(process.env.DCS_FRONTEND_PORT || 5173),
    proxy: {
      "/api": httpTarget,
      "/ws": { target: wsTarget, ws: true },
      "/stream": httpTarget,
    },
  },
});
