import { describe, expect, it } from "vitest";
import { DEFAULT_LANDING, safeNextPath } from "./safe-next";
import cases from "./safe-next.cases.json";

// FastAPI runs the same corpus: open redirects, encoded separators/dot
// segments, non-page routes and opaque query values must not drift.
describe("safeNextPath", () => {
  it.each(cases.keep)("keeps the shared browser/backend destination: %s", (value) => {
    expect(safeNextPath(value)).toBe(value);
  });

  it.each(cases.reject)("rejects the shared browser/backend destination: %s", (value) => {
    expect(safeNextPath(value)).toBe(DEFAULT_LANDING);
  });

  it("falls back when no destination is supplied", () => {
    expect(safeNextPath(undefined)).toBe(DEFAULT_LANDING);
  });
});
