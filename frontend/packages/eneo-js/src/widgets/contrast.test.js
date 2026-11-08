import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  contrastRatio,
  contrastVerdict,
  isHexColor,
  launcherColors,
  normalizeHexColor,
  themeColors
} from "./contrast.js";
describe("contrast", () => {
  it("computes the WCAG ratio", () => {
    assert.ok(Math.abs(contrastRatio("#000000", "#ffffff") - 21) < 0.5 * 10 ** -5);
    assert.ok(Math.abs(contrastRatio("#ffffff", "#000") - 21) < 0.5 * 10 ** -5);
    assert.ok(contrastRatio("#1F4E79", "#ffffff") > 7);
  });
  it("classifies the primary colour against white", () => {
    assert.deepStrictEqual(contrastVerdict("#1F4E79").verdict, "text");
    assert.deepStrictEqual(contrastVerdict("#e07a00").verdict, "graphics");
    assert.deepStrictEqual(contrastVerdict("#ffff00").verdict, "fail");
    assert.deepStrictEqual(contrastVerdict("blue").verdict, "invalid");
  });
  it("validates hex colours", () => {
    assert.deepStrictEqual(isHexColor("#abc"), true);
    assert.deepStrictEqual(isHexColor(" #ABCDEF "), true);
    assert.deepStrictEqual(isHexColor("#abcd"), false);
    assert.deepStrictEqual(isHexColor("rgb(0,0,0)"), false);
  });
  it("normalises colours to the #RRGGBB form the API stores", () => {
    assert.deepStrictEqual(normalizeHexColor("#abc"), "#AABBCC");
    assert.deepStrictEqual(normalizeHexColor(" #1f4 "), "#11FF44");
    assert.deepStrictEqual(normalizeHexColor("#abcdef"), "#ABCDEF");
    assert.deepStrictEqual(normalizeHexColor("#1F4E79"), "#1F4E79");
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
    assert.deepStrictEqual(themeColors(theme, false), { accent: "#1F4E79", header: "#EEF3F8" });
  });
  it("uses dark-mode colours where set and falls back per colour otherwise", () => {
    assert.deepStrictEqual(themeColors(theme, true), { accent: "#9CC7F0", header: "#EEF3F8" });
    assert.deepStrictEqual(themeColors({ primary_color: "#1F4E79" }, true), {
      accent: "#1F4E79",
      header: null
    });
  });
  it("gives the launcher a readable icon colour per scheme", () => {
    assert.deepStrictEqual(launcherColors(theme), {
      light: { accent: "#1F4E79", on_accent: "#FFFFFF" },
      dark: { accent: "#9CC7F0", on_accent: "#111111" }
    });
    assert.deepStrictEqual(
      launcherColors({ ...theme, color_scheme: "auto" }),
      launcherColors(theme)
    );
  });
  it("paints a widget pinned to one scheme in that scheme's colour on every host", () => {
    const lightOnly = { light: { accent: "#1F4E79", on_accent: "#FFFFFF" } };
    assert.deepStrictEqual(launcherColors({ ...theme, color_scheme: "light" }), {
      ...lightOnly,
      dark: lightOnly.light
    });
    const darkOnly = { accent: "#9CC7F0", on_accent: "#111111" };
    assert.deepStrictEqual(launcherColors({ ...theme, color_scheme: "dark" }), {
      light: darkOnly,
      dark: darkOnly
    });
  });
});
