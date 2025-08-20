import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig, loadEnv } from "vite";
import type { PluginOption } from "vite";
import tailwindcss from "@tailwindcss/vite";
// Visualiser to analyse bundle sizes
// import { visualizer } from "rollup-plugin-visualizer";

import { validateEnv, formatConfigSummary } from "./src/lib/config/core";
import { intricIcons } from "@intric/ui/icons/vite-plugin-intric-icons";
import { readFileSync } from "fs";
import { fileURLToPath } from "url";

const file = fileURLToPath(new URL("package.json", import.meta.url));
const json = readFileSync(file, "utf8");
const pkg = JSON.parse(json);

// Frontend configuration display plugin using shared core logic
function frontendConfigPlugin(): PluginOption {
  return {
    name: 'frontend-config-display',
    configureServer(server) {
      try {
        // Use Vite's loadEnv for proper environment loading
        const mode = server.config.mode || 'development';
        const envDir = server.config.envDir || process.cwd();
        const viteEnv = loadEnv(mode, envDir, '');
        
        // Merge with process.env (process.env takes precedence)
        const fullEnv = { ...viteEnv, ...process.env };
        
        // Use shared validation logic
        const result = validateEnv(fullEnv, { context: 'runtime' });
        
        // Display using shared formatting
        console.log(formatConfigSummary(result, { context: 'runtime' }));
      } catch (error) {
        console.warn('⚠️ Could not display frontend configuration:', (error as Error).message);
      }
    }
  };
}

export default defineConfig({
  plugins: [
    // visualizer({
    //   emitFile: true,
    //   filename: "stats.html"
    // }),
    frontendConfigPlugin() as PluginOption,
    tailwindcss() as PluginOption,
    intricIcons() as PluginOption,
    sveltekit() as PluginOption
  ],
  test: {
    include: ["src/**/*.{test,spec}.{js,ts}"]
  },
  server: {
    host: process.env.HOST ? "0.0.0.0" : undefined,
    port: 3000,
    strictPort: true
  },
  define: {
    __FRONTEND_VERSION__: JSON.stringify(pkg.version),
    __IS_PREVIEW__: process.env.CF_PAGES_BRANCH ? true : process.env.VERCEL_ENV === "preview",
    __GIT_BRANCH__: process.env.CF_PAGES_BRANCH
      ? `"${process.env.CF_PAGES_BRANCH}"`
      : `"${process.env.VERCEL_GIT_COMMIT_REF}"`,
    __GIT_COMMIT_SHA__: process.env.CF_PAGES_COMMIT_SHA
      ? `"${process.env.CF_PAGES_COMMIT_SHA}"`
      : `"${process.env.VERCEL_GIT_COMMIT_SHA}"`
  }
});
