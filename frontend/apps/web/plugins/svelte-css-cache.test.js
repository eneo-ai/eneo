import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createServer } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import { svelteCssCache } from "./svelte-css-cache.js";

for (const [component, selector] of [
  ["Dialog/Content.svelte", ".dialog-shadow"],
  ["Tooltip/Root.svelte", ".renderInline"]
]) {
  test(`serves cold and warm CSS for ${component}`, async () => {
    const cacheDir = await mkdtemp(join(tmpdir(), "eneo-css-test-"));
    const server = await createServer({
      configFile: false,
      root: fileURLToPath(new URL("../", import.meta.url)),
      cacheDir,
      logLevel: "silent",
      plugins: [tailwindcss(), svelteCssCache(), svelte({ configFile: false })],
      build: { target: "es2022" },
      optimizeDeps: { noDiscovery: true, include: [], esbuildOptions: { target: "es2022" } },
      server: { middlewareMode: true, watch: null, hmr: false }
    });
    try {
      await server.pluginContainer.buildStart({});
      const filename = fileURLToPath(
        new URL(`../../../packages/ui/src/lib/${component}`, import.meta.url)
      );
      const styleId = `${filename}?svelte&type=style&lang.css`;

      // Request styles first, as a browser with cached component modules can
      // do after a dev-server restart. The component has not been transformed.
      for (let request = 0; request < 2; request++) {
        const result = await server.transformRequest(styleId);
        assert.ok(result);
        assert.ok(result.code.includes(selector));
        assert.ok(result.code.includes("svelte-"), "CSS keeps Svelte's scoping");
        assert.ok(!result.code.includes("<script"), "Svelte source must never reach CSS output");
      }

      const raw = await server.transformRequest(`${filename}?raw`);
      assert.ok(raw?.code.includes("<script"), "raw component imports remain untouched");
    } finally {
      await server.close();
      await rm(cacheDir, { recursive: true, force: true });
    }
  });
}
