/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { describe, expect, it } from "vitest";
import { contrastRatio, contrastVerdict, isHexColor } from "./contrast";

describe("contrast", () => {
  it("computes the WCAG ratio", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrastRatio("#ffffff", "#000")).toBeCloseTo(21, 5);
    expect(contrastRatio("#1F4E79", "#ffffff")).toBeGreaterThan(7);
  });

  it("classifies the primary colour against white", () => {
    expect(contrastVerdict("#1F4E79").verdict).toBe("text");
    expect(contrastVerdict("#e07a00").verdict).toBe("graphics");
    expect(contrastVerdict("#ffff00").verdict).toBe("fail");
    expect(contrastVerdict("blue").verdict).toBe("invalid");
  });

  it("validates hex colours", () => {
    expect(isHexColor("#abc")).toBe(true);
    expect(isHexColor(" #ABCDEF ")).toBe(true);
    expect(isHexColor("#abcd")).toBe(false);
    expect(isHexColor("rgb(0,0,0)")).toBe(false);
  });
});
