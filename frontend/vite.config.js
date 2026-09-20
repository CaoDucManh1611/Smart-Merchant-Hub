import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { existsSync } from "node:fs";

const apiProxyTarget = process.env.VITE_PROXY_TARGET
  || (existsSync("/.dockerenv") ? "http://backend:8000" : "http://127.0.0.1:8000");

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    host: "0.0.0.0",
    allowedHosts: ["vocalist-dreamy-corned.ngrok-free.dev"],
    proxy: {
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      "/ws": {
        target: apiProxyTarget.replace(/^http/, "ws"),
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
