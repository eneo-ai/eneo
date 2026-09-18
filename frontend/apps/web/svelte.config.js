import adapter_node from "@sveltejs/adapter-node";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

// Impeccable's live picker loads from its local helper on :8400. Dev only: the
// array is empty in every other mode, so the built CSP is unchanged.
const DEV_LIVE = process.env.NODE_ENV === "development" ? ["http://localhost:8400"] : [];

/** @type {import('@sveltejs/kit').Config} */
const config = {
  // Consult https://kit.svelte.dev/docs/integrations#preprocessors
  // for more information about preprocessors
  preprocess: vitePreprocess(),
  kit: {
    // SvelteKit's generated/build dir, shared by `dev`, `build` and `preview`.
    // The E2E run (vite build + preview) overrides this to a separate dir so it
    // can't clobber a live `vite dev`'s `.svelte-kit` — letting tests and dev
    // coexist. See playwright.config.ts (SVELTE_KIT_OUT_DIR).
    outDir: process.env.SVELTE_KIT_OUT_DIR ?? ".svelte-kit",
    // Default build will generate a node version of the frontend
    adapter: adapter_node(),
    output: {
      // Server-rendered pages get their script preloads as <link rel="preload">
      // tags in the HTML. SvelteKit's default "modulepreload" strategy only
      // writes tags for prerendered pages and otherwise relies on a Link
      // response header, which this app strips because it grew past what the
      // reverse proxy accepts (#112, hooks.server.ts). ".mjs" avoids Chromium
      // parsing each module twice; adapter-node serves .mjs as JavaScript.
      preloadStrategy: "preload-mjs"
    },
    csp: {
      directives: {
        "script-src": ["self", ...DEV_LIVE],
        "script-src-elem": ["self", ...DEV_LIVE],
        "script-src-attr": ["self"],
        // Only in dev: the app had no connect-src directive, so adding one
        // outside dev would newly restrict where the client may call.
        ...(DEV_LIVE.length ? { "connect-src": ["self", ...DEV_LIVE] } : {})
      }
    },
    files: {
      params: "./src/lib/core/params"
    }
  }
};

export default config;
