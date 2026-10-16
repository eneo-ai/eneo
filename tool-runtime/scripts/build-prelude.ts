// Bundles what a script finds installed in the sandbox (src/tools/compute/prelude) into one
// plain script under dist/prelude. The engine evaluates it in every fresh context, so it has no
// imports left and is kept small; the libraries it holds are build-time dependencies only.
import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";
import { PRELUDE_PATH } from "../src/tools/compute/engine/prelude";

const MAX_PRELUDE_BYTES = 128 * 1024;

const result = await Bun.build({
  entrypoints: [new URL("../src/tools/compute/prelude/index.ts", import.meta.url).pathname],
  target: "browser",
  format: "esm",
  minify: true,
});
if (!result.success) throw new AggregateError(result.logs, "The prelude did not build");
const [artifact] = result.outputs;
if (!artifact) throw new Error("The prelude produced no output");
const code = await artifact.text();
if (/^\s*(import|export)\b/m.test(code)) throw new Error("The prelude still has imports or exports");
const bytes = Buffer.byteLength(code);
if (bytes > MAX_PRELUDE_BYTES)
  throw new Error(`The prelude is ${bytes} bytes; it is evaluated on every call and must stay under ${MAX_PRELUDE_BYTES}`);
await mkdir(dirname(PRELUDE_PATH), { recursive: true });
await Bun.write(PRELUDE_PATH, code);
console.log(`prelude: ${Math.round(bytes / 1024)} KB`);
