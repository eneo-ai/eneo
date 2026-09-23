// Writes dist/manifest.json next to the built loader: the version the web app
// serves under /widget/<version>/eneo.js, the floating channel it serves under
// /widget/<channel>/eneo.js, the SRI hash the admin snippet prints for pinned
// installs, and the sizes the budget below is enforced on.
// Then stops the build when the bytes differ from what release.json records
// for this version (see release.mjs); `--lock` records a new version instead,
// and `--dev` (the dev server's build of work in progress) skips the check.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { loaderChannel, lockRelease, releaseProblem } from "./release.mjs";

const GZIP_BUDGET_BYTES = 5 * 1024;

const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
const bundlePath = new URL("../dist/eneo.js", import.meta.url);
const source = readFileSync(bundlePath);
const gzipBytes = gzipSync(source, { level: 9 }).length;
const integrity = `sha384-${createHash("sha384").update(source).digest("base64")}`;

let channel;
try {
  channel = loaderChannel(pkg);
} catch (error) {
  console.error(error.message);
  process.exit(1);
}

const manifest = {
  version: pkg.version,
  channel,
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

const releasePath = new URL("../release.json", import.meta.url);
const locked = existsSync(releasePath) ? JSON.parse(readFileSync(releasePath, "utf8")) : null;
const built = { version: pkg.version, integrity };

if (process.argv.includes("--lock")) {
  const result = lockRelease(built, locked);
  if ("refused" in result) {
    console.error(result.refused);
    process.exit(1);
  }
  writeFileSync(releasePath, JSON.stringify(result.release, null, 2) + "\n");
  console.log(`release.json records ${built.version}`);
} else if (!process.argv.includes("--dev")) {
  const problem = releaseProblem(built, locked);
  if (problem) {
    console.error(problem);
    process.exit(1);
  }
}
