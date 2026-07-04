import { describe, expect, it } from "vitest";
import { formatBytes } from "./flowByteSize";

describe("formatBytes", () => {
  it("collapses zero, negative, and non-finite inputs to '0 B'", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(-1)).toBe("0 B");
    expect(formatBytes(Number.NaN)).toBe("0 B");
    expect(formatBytes(Number.POSITIVE_INFINITY)).toBe("0 B");
  });

  it("shows raw bytes with no decimals", () => {
    expect(formatBytes(1)).toBe("1 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1023)).toBe("1023 B");
  });

  it("scales at the 1024 boundary into KB, MB, and GB", () => {
    // A scaled value below 10 keeps one decimal, so an exact single unit
    // renders as "1.0", not "1".
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1024 * 1024)).toBe("1.0 MB");
    expect(formatBytes(1024 * 1024 * 1024)).toBe("1.0 GB");
  });

  it("caps at GB and does not roll over to TB", () => {
    // 1024 GB stays in GB (>= 10 drops the decimal) rather than becoming 1 TB.
    expect(formatBytes(1024 * 1024 * 1024 * 1024)).toBe("1024 GB");
  });

  it("keeps one decimal below 10 in a scaled unit", () => {
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(1.5 * 1024 * 1024)).toBe("1.5 MB");
  });

  it("drops the decimal at or above 10 in a scaled unit", () => {
    expect(formatBytes(10 * 1024)).toBe("10 KB");
    expect(formatBytes(200 * 1024 * 1024)).toBe("200 MB");
  });
});
