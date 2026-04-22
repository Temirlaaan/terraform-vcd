import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// When accessed through the shared nginx (https://tf-dashboard.t-cloud.kz)
// the browser sees port 443 / wss, but Vite internally runs on 5173.
// `hmr.clientPort` + `hmr.host` tell the HMR client where to connect.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
    allowedHosts: ["tf-dashboard.t-cloud.kz", "localhost"],
    hmr: {
      host: "tf-dashboard.t-cloud.kz",
      protocol: "wss",
      clientPort: 443,
    },
  },
});
