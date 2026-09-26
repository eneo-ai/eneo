import { describe, expect, it } from "vitest";
import { formatBytes } from "./format";

describe("formatBytes", () => {
  it("writes sizes the Swedish way", () => {
    expect(formatBytes(0, "sv")).toBe("0 B");
    expect(formatBytes(512, "sv")).toBe("512 B");
    expect(formatBytes(188_416, "sv")).toBe("184 kB");
    expect(formatBytes(1_258_291, "sv")).toBe("1,2 MB");
    expect(formatBytes(5 * 1024 ** 3, "sv")).toBe("5 GB");
  });

  it("writes sizes the English way", () => {
    expect(formatBytes(1_258_291, "en")).toBe("1.2 MB");
    expect(formatBytes(188_416, "en")).toBe("184 kB");
  });

  it("takes the number of decimals and moves up a unit instead of rounding to 1024", () => {
    expect(formatBytes(1_288_490, "sv", 2)).toBe("1,23 MB");
    expect(formatBytes(1024 * 1024 - 1, "sv")).toBe("1 MB");
  });

  it("shows nothing stored for sizes that are not a positive number", () => {
    expect(formatBytes(-1, "sv")).toBe("0 B");
    expect(formatBytes(Number.NaN, "sv")).toBe("0 B");
  });
});
