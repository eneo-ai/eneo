import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(new URL("check-server-bundle.mjs", import.meta.url));

function check(files) {
  const build = mkdtempSync(join(tmpdir(), "server-bundle-"));
  for (const [path, source] of Object.entries(files)) {
    mkdirSync(dirname(join(build, path)), { recursive: true });
    writeFileSync(join(build, path), source);
  }
  return spawnSync(process.execPath, [script, build], { encoding: "utf8" });
}

const handler = 'import { createReadStream } from "node:fs";\nimport path from "path";\n';

test("passes when the server imports only Node built-ins and its own chunks", () => {
  const result = check({
    "handler.js": handler,
    "server/index.js": "export const a = 1;\n",
    "server/chunks/lazy.js": "export default 2;\n",
    "server/chunks/page.js": [
      'import { a } from "../index.js";',
      'const lazy = () => import("./lazy.js");',
      "/** @type {import('@sveltejs/kit').Handle} */",
      'const text = "import x from \\"left-pad\\"";',
      "const html = `",
      'import y from "sirv";',
      '<script>import("${path}")</script>`;'
    ].join("\n"),
    "client/app.js": 'import "browser-only-package";\n'
  });
  assert.equal(result.status, 0, result.stderr);
});

test("fails on a package that stayed external, naming it and its importer", () => {
  const result = check({
    "handler.js": handler,
    "server/chunks/page.js": 'import Paragraph from "@tiptap/extension-paragraph";\n',
    "server/chunks/lazy.js": 'const m = await import("paneforge/dist/index.js");\n'
  });
  assert.equal(result.status, 1);
  assert.match(
    result.stderr,
    /@tiptap\/extension-paragraph\n\s+imported by server\/chunks\/page\.js/
  );
  assert.match(result.stderr, /paneforge\/dist\/index\.js/);
});

test("fails when there is no build to check", () => {
  const result = check({ "server/index.js": "" });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /No adapter-node build/);
});
