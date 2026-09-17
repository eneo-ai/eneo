/* eslint-disable eneo/no-raw-color -- fixtures use literal widget colours */
import { describe, expect, it } from "vitest";
import {
  contrastRatio,
  contrastVerdict,
  isHexColor,
  launcherColors,
  themeColors
} from "./contrast";

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

describe("themeColors", () => {
  const theme = {
    primary_color: "#1F4E79",
    header_color: "#EEF3F8",
    primary_color_dark: "#9CC7F0",
    header_color_dark: null
  };

  it("uses the light-mode colours in light mode", () => {
    expect(themeColors(theme, false)).toEqual({ accent: "#1F4E79", header: "#EEF3F8" });
  });

  it("uses dark-mode colours where set and falls back per colour otherwise", () => {
    expect(themeColors(theme, true)).toEqual({ accent: "#9CC7F0", header: "#EEF3F8" });
    expect(themeColors({ primary_color: "#1F4E79" }, true)).toEqual({
      accent: "#1F4E79",
      header: null
    });
  });

  it("gives the launcher a readable icon colour per scheme", () => {
    expect(launcherColors(theme)).toEqual({
      light: { accent: "#1F4E79", on_accent: "#FFFFFF" },
      dark: { accent: "#9CC7F0", on_accent: "#111111" }
    });
  });
});
