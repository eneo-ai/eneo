import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { describe, it } from "node:test";
import { readFileSync } from "node:fs";
import { loaderChannel, lockRelease, releaseProblem } from "./release.mjs";

const shipped = { version: "1.0.0", integrity: "sha384-shipped" };
const registry = { releases: [shipped] };
const hash = (bytes) => `sha384-${createHash("sha384").update(bytes).digest("base64")}`;

describe("built assets", () => {
  it("pins the CSS fetched by the SRI-protected script", () => {
    const script = readFileSync(new URL("../dist/eneo.js", import.meta.url));
    const css = readFileSync(new URL("../dist/eneo.css", import.meta.url));
    const manifest = JSON.parse(readFileSync(new URL("../dist/manifest.json", import.meta.url)));
    const locked = JSON.parse(readFileSync(new URL("../release.json", import.meta.url)));

    assert.equal(manifest.integrity, hash(script));
    assert.equal(manifest.css_integrity, hash(css));
    assert.ok(script.toString().includes(manifest.css_integrity));
    assert.deepEqual(locked.releases.at(-1), {
      version: manifest.version,
      integrity: manifest.integrity,
      css_integrity: manifest.css_integrity
    });
  });
});

describe("releaseProblem", () => {
  it("lets the recorded bytes of the recorded version through", () => {
    assert.equal(releaseProblem(shipped, registry), null);
  });

  it("stops new bytes under a version whose pinned URL already exists", () => {
    const problem = releaseProblem({ version: "1.0.0", integrity: "sha384-changed" }, registry);
    assert.match(problem ?? "", /bytes changed but its version is still 1\.0\.0/);
  });

  it("stops a changed stylesheet under the same pinned version", () => {
    const locked = { releases: [{ ...shipped, css_integrity: "sha384-style-old" }] };
    const built = { ...shipped, css_integrity: "sha384-style-new" };
    assert.match(releaseProblem(built, locked) ?? "", /bytes changed/);
    assert.ok("refused" in lockRelease(built, locked));
  });

  it("stops a bumped version that was never recorded", () => {
    const problem = releaseProblem({ version: "1.0.1", integrity: "sha384-changed" }, registry);
    assert.match(problem ?? "", /release\.json records 1\.0\.0/);
  });

  it("stops a build without a record", () => {
    assert.match(releaseProblem(shipped, null) ?? "", /missing/);
    assert.match(releaseProblem(shipped, { releases: [] }) ?? "", /missing/);
  });
});

describe("lockRelease", () => {
  it("records a new version and its bytes", () => {
    const built = {
      version: "1.0.1",
      integrity: "sha384-new",
      css_integrity: "sha384-css"
    };
    assert.deepEqual(lockRelease(built, registry), { release: { releases: [shipped, built] } });
    assert.deepEqual(lockRelease(built, null), { release: { releases: [built] } });
  });

  it("refuses to give a recorded version other bytes", () => {
    const result = lockRelease({ version: "1.0.0", integrity: "sha384-changed" }, registry);
    assert.ok("refused" in result);
  });

  it("refuses to make an archived version current again", () => {
    const newer = { version: "1.0.1", integrity: "sha384-new" };
    const result = lockRelease(shipped, { releases: [shipped, newer] });
    assert.ok("refused" in result);
  });
});

describe("loaderChannel", () => {
  it("stays v1, the address every floating snippet already pasted into a site loads", () => {
    const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
    assert.equal(loaderChannel(pkg), "v1");
  });

  it("does not follow the version", () => {
    assert.equal(loaderChannel({ version: "2.0.0", eneoWidgetChannel: "v1" }), "v1");
  });

  it("refuses a package without a channel", () => {
    assert.throws(() => loaderChannel({}), /eneoWidgetChannel/);
    assert.throws(() => loaderChannel({ eneoWidgetChannel: "1" }), /eneoWidgetChannel/);
    assert.throws(() => loaderChannel({ eneoWidgetChannel: "latest" }), /eneoWidgetChannel/);
  });
});
