import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { readFileSync } from "node:fs";
import { loaderChannel, lockRelease, releaseProblem } from "./release.mjs";

const shipped = { version: "1.0.0", integrity: "sha384-shipped" };

describe("releaseProblem", () => {
  it("lets the recorded bytes of the recorded version through", () => {
    assert.equal(releaseProblem(shipped, shipped), null);
  });

  it("stops new bytes under a version whose pinned URL already exists", () => {
    const problem = releaseProblem({ version: "1.0.0", integrity: "sha384-changed" }, shipped);
    assert.match(problem ?? "", /bytes changed but its version is still 1\.0\.0/);
  });

  it("stops a bumped version that was never recorded", () => {
    const problem = releaseProblem({ version: "1.0.1", integrity: "sha384-changed" }, shipped);
    assert.match(problem ?? "", /release\.json records 1\.0\.0/);
  });

  it("stops a build without a record", () => {
    assert.match(releaseProblem(shipped, null) ?? "", /missing/);
    assert.match(releaseProblem(shipped, { version: "1.0.0" }) ?? "", /missing/);
  });
});

describe("lockRelease", () => {
  it("records a new version and its bytes", () => {
    const built = { version: "1.0.1", integrity: "sha384-new" };
    assert.deepEqual(lockRelease(built, shipped), { release: built });
    assert.deepEqual(lockRelease(built, null), { release: built });
  });

  it("refuses to give a recorded version other bytes", () => {
    const result = lockRelease({ version: "1.0.0", integrity: "sha384-changed" }, shipped);
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
