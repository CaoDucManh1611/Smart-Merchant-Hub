import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { localizeVueTemplatePlugin } from "./src/i18n-vue-plugin.js";

// https://vite.dev/config/
export default defineConfig({
  plugins: [localizeVueTemplatePlugin(), vue()],
  server: {
    host: "0.0.0.0",
    allowedHosts: ["vocalist-dreamy-corned.ngrok-free.dev"],
    proxy: {
      "/api": {
        target: "http://backend:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://backend:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
