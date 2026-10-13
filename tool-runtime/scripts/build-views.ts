// Builds every tool view into one self-contained HTML page under dist/views. A view runs in
// the host's sandboxed frame with no network, so its script and styles are inlined.
import { mkdir, rm } from "node:fs/promises";
import { join } from "node:path";
import { build } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";
import { VIEWS_DIRECTORY } from "../src/views/load";

const ROOT = join(import.meta.dir, "..");
/** Each view by the name it is loaded under, and the directory its page lives in. */
const VIEWS = {
  "query-result": "src/tools/tabular/view",
  chart: "src/tools/charts/view",
};
// Eneo reads a view only up to this size (mcp_app_resource_max_bytes in its backend).
const MAX_VIEW_BYTES = 2 * 1024 * 1024;

await rm(VIEWS_DIRECTORY, { recursive: true, force: true });
await mkdir(VIEWS_DIRECTORY, { recursive: true });
for (const [name, directory] of Object.entries(VIEWS)) {
  const result = await build({
    configFile: false,
    root: join(ROOT, directory),
    logLevel: "warn",
    plugins: [viteSingleFile()],
    build: {
      write: false,
      target: "es2022",
      rollupOptions: {
        // Astryx marks its modules for server rendering; a page built whole has no use for it.
        onwarn: (warning, warn) => {
          if (warning.code !== "MODULE_LEVEL_DIRECTIVE") warn(warning);
        },
      },
    },
  });
  const outputs = (Array.isArray(result) ? result : [result]).flatMap((entry) =>
    "output" in entry ? entry.output : [],
  );
  const page = outputs.find((output) => output.type === "asset" && output.fileName === "index.html");
  if (!page || page.type !== "asset") throw new Error(`The ${name} view produced no page`);
  const html = String(page.source);
  const bytes = Buffer.byteLength(html);
  if (bytes > MAX_VIEW_BYTES)
    throw new Error(`The ${name} view is ${bytes} bytes; a host reads at most ${MAX_VIEW_BYTES}`);
  await Bun.write(join(VIEWS_DIRECTORY, `${name}.html`), html);
  console.log(`${name}: ${Math.round(bytes / 1024)} KB`);
}
