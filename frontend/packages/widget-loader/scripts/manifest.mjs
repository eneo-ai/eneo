// Writes dist/manifest.json next to the built loader: the version the web app
// serves under /widget/<version>/eneo.js, the SRI hash the admin snippet
// prints for pinned installs, and the sizes the budget below is enforced on.
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const GZIP_BUDGET_BYTES = 5 * 1024;

const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const bundlePath = new URL("../dist/eneo.js", import.meta.url);
const source = readFileSync(bundlePath);
const gzipBytes = gzipSync(source, { level: 9 }).length;
const integrity = `sha384-${createHash("sha384").update(source).digest("base64")}`;

const manifest = {
  version: pkg.version,
  file: "eneo.js",
  integrity,
  bytes: source.length,
  gzip_bytes: gzipBytes
};
writeFileSync(
  new URL("../dist/manifest.json", import.meta.url),
  JSON.stringify(manifest, null, 2) + "\n"
);

console.log(`eneo.js ${manifest.bytes} B (${gzipBytes} B gzip), ${integrity}`);
if (gzipBytes > GZIP_BUDGET_BYTES) {
  console.error(
    `Loader exceeds its ${GZIP_BUDGET_BYTES} B gzip budget by ${gzipBytes - GZIP_BUDGET_BYTES} B`
  );
  process.exit(1);
}
