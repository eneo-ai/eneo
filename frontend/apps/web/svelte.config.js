import adapter_node from "@sveltejs/adapter-node";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/** @type {import('@sveltejs/kit').Config} */
const config = {
  // Consult https://kit.svelte.dev/docs/integrations#preprocessors
  // for more information about preprocessors
  preprocess: vitePreprocess(),
  kit: {
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
