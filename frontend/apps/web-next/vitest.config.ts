import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src")
    }
  },
  test: {
    // Server-side logic runs under node (jose/oauth4webapi reject jsdom's
    // cross-realm Uint8Array); component tests opt into jsdom per file.
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    env: {
      // env.ts validates at import time; give tests a valid baseline
      ENEO_BACKEND_URL: "http://localhost:8123",
      SESSION_SECRET: "vitest-session-secret-32-chars-min!!"
    }
  }
});
