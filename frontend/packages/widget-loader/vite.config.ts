import { readFileSync } from "node:fs";
import { defineConfig, type Plugin } from "vitest/config";
import { minifyCss } from "./scripts/minify-css.mjs";

const pkg = JSON.parse(readFileSync(new URL("package.json", import.meta.url), "utf8")) as {
  version: string;
};

const STYLES_LITERAL = /(export const styles = `)([\s\S]*?)(`;)/;

/** The stylesheet string ships collapsed; esbuild leaves string contents alone. */
function minifyStyles(): Plugin {
  return {
    name: "eneo-minify-styles",
    apply: "build",
    transform(code, id) {
      if (!id.endsWith("/src/styles.ts")) return null;
      return code.replace(STYLES_LITERAL, (_, open, css, close) => open + minifyCss(css) + close);
    }
  };
}

// A classic IIFE for every CMS: no module syntax, no polyfills, es2019 so the
// bundle stays small and runs in anything that has custom elements. The
// target applies to the shipped bundle only; Vitest's dev server pre-bundles
// modern test tooling that must not be downlevelled.
export default defineConfig(({ command }) => ({
  define: {
    __LOADER_VERSION__: JSON.stringify(pkg.version)
  },
  plugins: [minifyStyles()],
  optimizeDeps: {
    esbuildOptions: { target: "es2022" }
  },
  build:
    command === "build"
      ? {
          target: "es2019",
          outDir: "dist",
          emptyOutDir: true,
          minify: "esbuild",
          sourcemap: false,
          lib: {
            entry: "src/index.ts",
            formats: ["iife"],
            name: "EneoWidgetLoader",
            fileName: () => "eneo.js"
          }
        }
      : {},
  test: {
    include: ["src/**/*.test.ts"],
    browser: {
      enabled: true,
      provider: "playwright",
      headless: true,
      instances: [{ browser: "chromium" }]
    }
  }
}));
