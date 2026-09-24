import { readFileSync } from "node:fs";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

const pkg = JSON.parse(readFileSync(new URL("package.json", import.meta.url), "utf8")) as {
  version: string;
};

/**
 * The shadow root's CSS is a template literal, which esbuild leaves as
 * written. Drop its comments and collapse whitespace in the shipped bundle;
 * spaces inside selectors and `calc()` stay single spaces.
 */
function minifyShadowCss(): Plugin {
  return {
    name: "eneo-minify-shadow-css",
    apply: "build",
    transform(code, id) {
      if (!id.endsWith("/src/styles.ts")) return null;
      return code.replace(
        /(styles = `)([\s\S]*?)(`)/,
        (_, open: string, css: string, close: string) =>
          open +
          css
            .replace(/\/\*[\s\S]*?\*\//g, "")
            .replace(/\s+/g, " ")
            .replace(/\s*([{};,])\s*/g, "$1")
            .replace(/;}/g, "}")
            .trim() +
          close
      );
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
  plugins: [minifyShadowCss()],
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
