import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { lockRelease, releaseProblem } from "./release.mjs";

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
