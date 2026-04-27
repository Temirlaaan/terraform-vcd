import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  ...(mode === "development"
    ? {
        server: {
          port: 5173,
          host: "0.0.0.0",
          allowedHosts: ["tf-dashboard.t-cloud.kz", "localhost"],
        },
      }
    : {}),
}));
