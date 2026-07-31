import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vitest/config";
import { searchForWorkspaceRoot, type PluginOption } from "vite";
import tailwindcss from "@tailwindcss/vite";
import { paraglideVitePlugin } from "@inlang/paraglide-js";

import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { eneoIcons } from "@eneo/ui/icons/vite-plugin-eneo-icons";

const file = fileURLToPath(new URL("package.json", import.meta.url));
const json = readFileSync(file, "utf8");
const pkg = JSON.parse(json);
const browserTarget = "es2022";

export default defineConfig({
  cacheDir: process.env.VITEST ? "node_modules/.vitest" : "node_modules/.vite-web",
  build: {
    target: browserTarget,
    reportCompressedSize: false
  },
  optimizeDeps: {
    esbuildOptions: {
      target: browserTarget
    }
  },
  plugins: [
    // Paraglide's change detection is in-memory only, so every fresh process
    // rewrites the whole catalog under src/lib/paraglide. Vitest loads this
    // shared config once per project; compiling from each project can expose a
    // half-written catalog to another project. The test lifecycle compiles the
    // catalog once before Vitest starts. Other secondary tooling can set
    // PARAGLIDE_SKIP_COMPILE=1 to leave a running dev server undisturbed.
    ...(process.env.PARAGLIDE_SKIP_COMPILE || process.env.VITEST
      ? []
      : [
          paraglideVitePlugin({
            project: "./project.inlang",
            outdir: "./src/lib/paraglide",
            strategy: ["url", "cookie", "baseLocale"],
            // This catalogue contains thousands of messages. Paraglide's
            // large-project structure keeps one generated module per locale
            // instead of making Vite retain one module per message.
            outputStructure: "locale-modules"
          }) as PluginOption
        ]),
    tailwindcss() as PluginOption,
    eneoIcons() as PluginOption,
    sveltekit() as PluginOption
  ],
  test: {
    // Coverage merges across both projects below into one report. Source maps
    // back to .ts/.svelte; generated and test files are excluded. lcov feeds
    // diff-cover in CI, json-summary is the machine-readable total, html is for
    // humans. Run via `bun run test:coverage`.
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov", "json-summary"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,js,svelte}"],
      exclude: [
        "src/**/*.{test,spec}.{js,ts}",
        "src/**/*.d.ts",
        "src/lib/paraglide/**" // generated i18n catalogs
      ]
    },
    // Three Vitest projects share the Vite/SvelteKit setup above via `extends`:
    //   - client: component tests (*.svelte.test.ts) in a real Chromium via Playwright
    //   - dom: deterministic high-volume component wiring tests (*.dom.test.ts) in jsdom
    //   - server: pure unit tests (*.test.ts) in Node
    // Component tests need a real DOM because Svelte 5 runes/$effect/transitions
    // misbehave under jsdom; the server project keeps unit tests fast.
    projects: [
      {
        extends: "./vite.config.ts",
        test: {
          name: "client",
          // No `environment`: browser mode runs in a real Chromium, so Vitest
          // ignores the jsdom/node environment field here.
          browser: {
            enabled: true,
            provider: "playwright",
            headless: true,
            instances: [{ browser: "chromium" }]
          },
          include: ["src/**/*.svelte.{test,spec}.{js,ts}"],
          exclude: ["src/lib/server/**"]
        }
      },
      {
        extends: "./vite.config.ts",
        resolve: {
          conditions: ["browser"]
        },
        test: {
          name: "dom",
          environment: "jsdom",
          include: ["src/**/*.dom.{test,spec}.{js,ts}"]
        }
      },
      {
        extends: "./vite.config.ts",
        test: {
          name: "server",
          environment: "node",
          include: ["src/**/*.{test,spec}.{js,ts}"],
          exclude: ["src/**/*.svelte.{test,spec}.{js,ts}", "src/**/*.dom.{test,spec}.{js,ts}"]
        }
      }
    ]
  },
  server: {
    host: "0.0.0.0", // Change to host 0.0.0.0 if you cant login on localhost (e.g. WSL)
    port: 3000,
    strictPort: true,
    fs: {
      // Allow the dev server to serve files from the monorepo root so workspace
      // packages like @eneo/ui (icons in packages/ui/src/icons/svg) load
      // without "outside of Vite serving allow list" errors.
      allow: [searchForWorkspaceRoot(process.cwd())]
    },
    watch: {
      usePolling: true,
      interval: 1000,
      // E2E tooling writes thousands of files into these while a dev server
      // runs; none of them belong to the dev module graph.
      ignored: ["**/.svelte-kit-e2e/**", "**/test-results/**", "**/playwright-report/**"]
    }
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
  },
  // Bundle these runtime deps into the SSR output so the production node
  // runner can find them. The frontend Dockerfile's runner stage copies
  // apps/web/build + apps/web/package.json but DOES NOT install node_modules,
  // so anything Vite externalizes for SSR (i.e. listed in apps/web/dependencies)
  // crashes at startup with ERR_MODULE_NOT_FOUND on the first SSR render that
  // needs it. marked + dompurify were added to apps/web/dependencies for the
  // Prompt Guide markdown component; without `noExternal` here they would be
  // externalized, and the chat page (which renders messages via @eneo/ui's
  // Markdown, also using marked) would 500 on hard refresh.
  ssr: {
    noExternal: ["@xyflow/svelte", "@xyflow/system", "marked", "dompurify", "zod"]
  }
});
