import { describe, expect, it } from "vitest";
import { contrastRatio, MODES, over, parseColor, tokenColor } from "./contrast-math";

describe("contrast maths", () => {
  it("matches the WCAG reference values", () => {
    const white = parseColor("#FFFFFF");
    expect(contrastRatio(parseColor("#000"), white)).toBeCloseTo(21, 5);
    expect(contrastRatio(parseColor("#767676"), white)).toBeCloseTo(4.54, 2);
    expect(contrastRatio(parseColor("#FFFFFF"), white)).toBe(1);
    // The ratio does not depend on which colour is the foreground.
    expect(contrastRatio(white, parseColor("#767676"))).toBeCloseTo(4.54, 2);
  });

  it("composites translucent colours over their background", () => {
    const halfBlack = parseColor("rgba(0, 0, 0, 0.5)");
    expect(over(halfBlack, parseColor("#FFFFFF"))).toEqual({ r: 127.5, g: 127.5, b: 127.5, a: 1 });
    expect(parseColor("#FF000080").a).toBeCloseTo(0.5, 2);
    // A translucent foreground is judged as painted on its background.
    expect(contrastRatio(halfBlack, parseColor("#FFFFFF"))).toBeCloseTo(
      contrastRatio(parseColor("#808080"), parseColor("#FFFFFF")),
      1
    );
  });

  it("reads both colour modes from light-dark() and follows var() references", () => {
    const tokens = {
      "--a": "light-dark(#fff, rgba(1, 2, 3, 0.5))",
      "--b": "light-dark(var(--a), #000)"
    };
    expect(tokenColor(tokens, "--a", MODES[0])).toEqual({ r: 255, g: 255, b: 255, a: 1 });
    expect(tokenColor(tokens, "--a", MODES[1])).toEqual({ r: 1, g: 2, b: 3, a: 0.5 });
    expect(tokenColor(tokens, "--b", MODES[0])).toEqual({ r: 255, g: 255, b: 255, a: 1 });
    expect(() => tokenColor(tokens, "--missing", MODES[0])).toThrow(/Unknown token/);
    expect(() => parseColor("oklab(0.5 0 0)")).toThrow(/Unsupported colour/);
  });
});
