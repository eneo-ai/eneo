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
    // Pure logic runs under Node; component tests opt into jsdom per file.
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    // What jsdom lacks and Astryx needs (modal <dialog>, CSS.escape, …).
    setupFiles: ["./src/test/setup-dom.ts"],
    env: {
      TZ: "Asia/Kolkata"
    }
  }
});
