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

  it("falls back for empty / nullish", () => {
    expect(safeNextPath("")).toBe(DEFAULT_LANDING);
    expect(safeNextPath(null)).toBe(DEFAULT_LANDING);
    expect(safeNextPath(undefined)).toBe(DEFAULT_LANDING);
  });
});
