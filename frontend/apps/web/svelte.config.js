import adapter_node from "@sveltejs/adapter-node";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

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
    csp: {
      directives: {
        "script-src": ["self"],
        "script-src-elem": ["self"],
        "script-src-attr": ["self"]
      }
    },
    files: {
      params: "./src/lib/core/params"
    }
  }
};

export default config;
