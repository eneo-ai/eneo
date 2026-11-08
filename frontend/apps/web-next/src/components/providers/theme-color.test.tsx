// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { ThemeProvider } from "next-themes";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { surfaceColors } from "@/theme/surface-colors";
import { ThemeColor } from "./theme-color";

const { light, dark } = surfaceColors();

// The two tags the root layout's viewport export renders.
beforeEach(() => {
  for (const [media, color] of [
    ["(prefers-color-scheme: light)", light],
    ["(prefers-color-scheme: dark)", dark]
  ] as const) {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    meta.media = media;
    meta.content = color;
    document.head.append(meta);
  }
});
afterEach(() => {
  document.head.querySelectorAll('meta[name="theme-color"]').forEach((meta) => meta.remove());
  localStorage.clear();
});

const contents = () =>
  [...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]')].map((m) => m.content);

describe("ThemeColor", () => {
  it("paints the status bar in the chosen mode when Tema is Mörkt or Ljust", () => {
    render(
      <ThemeProvider attribute="class" defaultTheme="dark" enableSystem>
        <ThemeColor />
      </ThemeProvider>
    );
    expect(contents()).toEqual([dark, dark]);
  });

  it("leaves each tag on its own scheme's colour when Tema is System", () => {
    render(
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
        <ThemeColor />
      </ThemeProvider>
    );
    expect(contents()).toEqual([light, dark]);
  });
});
