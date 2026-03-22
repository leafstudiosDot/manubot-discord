import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const packageJsonPath = resolve(__dirname, "package.json");
const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf-8"));
const appVersion = `v${packageJson.version}`;

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion)
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:6540",
        changeOrigin: true
      },
      "/ws": {
        target: "ws://localhost:6540",
        ws: true,
        changeOrigin: true
      }
    }
  }
});
