import path from "node:path";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Vite build of the SPA (`bun run build:vite`); Next still owns `dev`,
// `build` and `start`. Tests keep their own vitest.config.mts, without the
// router plugin, so a test run never rewrites the route tree.
export default defineConfig({
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
      { find: /^@\//, replacement: `${path.resolve(import.meta.dirname, "src")}/` }
    ]
  },
  // FastAPI replaces the placeholder with each response's CSP nonce.
  html: { cspNonce: "__ENEO_CSP_NONCE__" }
});
