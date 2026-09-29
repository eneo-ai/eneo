import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { defineConfig, type Plugin } from "vitest/config";
import { playwright } from "@vitest/browser-playwright";
import { minifyCss } from "./scripts/minify-css.mjs";
import { styles } from "./src/styles";

const pkg = JSON.parse(readFileSync(new URL("package.json", import.meta.url), "utf8")) as {
  version: string;
};
const stylesheet = minifyCss(styles);
const cssIntegrity = `sha384-${createHash("sha384").update(stylesheet).digest("base64")}`;

/** The shadow root loads this stylesheet from the Eneo origin under the host CSP. */
function emitStyles(): Plugin {
  return {
    name: "eneo-emit-styles",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "eneo.css", source: stylesheet });
    }
  };
}

// A classic IIFE for every CMS: no module syntax, no polyfills, es2019 so the
// bundle stays small and runs in anything that has custom elements. The
// target applies to the shipped bundle only; Vitest's dev server pre-bundles
// modern test tooling that must not be downlevelled.
export default defineConfig(({ command }) => ({
  define: {
    __LOADER_VERSION__: JSON.stringify(pkg.version),
    __LOADER_CSS_INTEGRITY__: JSON.stringify(cssIntegrity)
  },
  plugins: [emitStyles()],
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
      provider: playwright(),
      headless: true,
      instances: [{ browser: "chromium" }]
    }
  }
}));
