import path from "node:path";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type ServerOptions } from "vite";

// The Vite build of the SPA (`bun run build:vite`) and its dev server
// (`bun run dev:vite`); Next still owns `dev`, `build` and `start`. Tests keep
// their own vitest.config.mts, without the router plugin, so a test run never
// rewrites the route tree.
export default defineConfig(({ command, mode }) => ({
  plugins: [
    // Paths come from tsr.config.json, shared with the `tsr` CLI. The plugin
    // reads that file from process.cwd() when it is constructed, so the build
    // flags are inline: route splitting must not depend on where Vite starts.
    // It must come before the React plugin so route files are split before
    // JSX is transformed.
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react()
  ],
  resolve: {
    // Ordered: the first match wins, so specific aliases go before `@/`.
    alias: [
      // @streamdown/code imports Shiki's full `bundledLanguages` (235
      // grammars, one chunk each); the web bundle keeps 57 common ones and
      // other fences fall back to plain text. Only bare `shiki` is matched, so
      // `shiki/engine/javascript` still resolves normally.
      { find: /^shiki$/, replacement: "shiki/bundle/web" },
      {
        find: /^@\/lib\/api\/base$/,
        replacement: path.resolve(import.meta.dirname, "src/lib/api/base.vite.ts")
      },
      // The navigation seam's TanStack implementation; vitest keeps the Next
      // one (feature tests mock the seam with @/test/navigation).
      {
        find: /^@\/lib\/navigation$/,
        replacement: path.resolve(import.meta.dirname, "src/lib/navigation.tanstack.ts")
      },
      {
        find: /^@\/lib\/link$/,
        replacement: path.resolve(import.meta.dirname, "src/lib/link.tanstack.tsx")
      },
      { find: /^@\//, replacement: `${path.resolve(import.meta.dirname, "src")}/` }
    ]
  },
  // FastAPI replaces the placeholder with each response's CSP nonce. The dev
  // server sends no CSP: it is checked against the FastAPI-served build.
  html: { cspNonce: "__ENEO_CSP_NONCE__" },
  server: command === "serve" ? devServer(mode) : undefined
}));

// The browser stays on the dev server's origin and the backend paths are
// proxied to FastAPI, so the session cookie, the Sec-Fetch-Site gate and the
// WebSocket Origin check behave as in production. changeOrigin stays false:
// the backend sees the browser's Host, as it does behind Traefik.
function devServer(mode: string): ServerOptions {
  // Only this variable: an empty prefix would load every secret in the env.
  const target = loadEnv(mode, import.meta.dirname, "ENEO_BACKEND_URL").ENEO_BACKEND_URL;
  if (!target) {
    throw new Error("Set ENEO_BACKEND_URL (see .env.example) to the backend for the dev server");
  }
  const backend = { target, changeOrigin: false };
  // Whole path segments, matched against the path and query.
  return {
    port: 3101,
    strictPort: true,
    proxy: {
      "^/api(?:[/?]|$)": { ...backend, ws: true },
      "^/version(?:[/?]|$)": backend,
      "^/(?:login|auth)/callback(?:[/?]|$)": backend
    }
  };
}
