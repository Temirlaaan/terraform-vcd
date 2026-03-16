import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://10.121.245.146:8000",
      "/ws": {
        target: "ws://10.121.245.146:8000",
        ws: true,
      },
    },
  },
});
