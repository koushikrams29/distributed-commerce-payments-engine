/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const gateway = process.env.GATEWAY_URL ?? "http://localhost:8001";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Same-origin in development: the browser talks to Vite, Vite forwards to
    // the gateway, so no CORS configuration is needed locally.
    proxy: {
      "/api": { target: gateway, changeOrigin: true },
      "/ws": { target: gateway, changeOrigin: true, ws: true },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
