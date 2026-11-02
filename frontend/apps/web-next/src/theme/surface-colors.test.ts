import { describe, expect, it } from "vitest";
import { eneoTheme } from "./eneo";
import { surfaceColors } from "./surface-colors";

describe("surfaceColors", () => {
  it("splits the built surface token into its light and dark colours", () => {
    const { light, dark } = surfaceColors();
    expect(eneoTheme.tokens["--color-background-surface"]).toBe(`light-dark(${light}, ${dark})`);
    expect(light).toMatch(/^#[0-9A-F]{6}$/i);
    expect(dark).toMatch(/^#[0-9A-F]{6}$/i);
    expect(light).not.toBe(dark);
  });
});
