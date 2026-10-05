import { describe, expect, it } from "vitest";
import { DEFAULT_LANDING, safeNextPath } from "./safe-next";

describe("safeNextPath", () => {
  it("keeps same-origin absolute paths", () => {
    expect(safeNextPath("/dashboard")).toBe("/dashboard");
    expect(safeNextPath("/spaces/personal/chat?tab=chat")).toBe("/spaces/personal/chat?tab=chat");
    expect(safeNextPath("/")).toBe("/");
  });

  it("rejects protocol-relative and backslash tricks (open redirect)", () => {
    expect(safeNextPath("//evil.com")).toBe(DEFAULT_LANDING);
    expect(safeNextPath("/\\evil.com")).toBe(DEFAULT_LANDING);
  });

  it("rejects absolute URLs and non-paths", () => {
    expect(safeNextPath("https://evil.com")).toBe(DEFAULT_LANDING);
    expect(safeNextPath("evil.com")).toBe(DEFAULT_LANDING);
  });

  it.each([
    "/\n/evil.example",
    "/\t/evil.example",
    "/%2fexample.com",
    "/%5cexample.com",
    "/bad%escape",
    "/ok\u007f"
  ])("rejects ambiguous browser destinations: %s", (value) =>
    expect(safeNextPath(value)).toBe(DEFAULT_LANDING)
  );

  it("preserves opaque query encoding after validation", () => {
    const next = "/module-login?state=a%2Bb%252Fc";
    expect(safeNextPath(next)).toBe(next);
  });

  it("falls back for empty / nullish", () => {
    expect(safeNextPath("")).toBe(DEFAULT_LANDING);
    expect(safeNextPath(null)).toBe(DEFAULT_LANDING);
    expect(safeNextPath(undefined)).toBe(DEFAULT_LANDING);
  });
});
