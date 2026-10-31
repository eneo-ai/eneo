// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { afterEach, expect, it, vi } from "vitest";
import { eneoTheme } from "@/theme/eneo";
import { surfaceColors } from "@/theme/surface-colors";

const html = readFileSync(resolve("index.html"), "utf8");
const template = new DOMParser().parseFromString(html, "text/html");

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.className = "";
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("style");
});

it("preserves the responsive document metadata and fixed server placeholders", () => {
  expect(template.documentElement.lang).toBe("__ENEO_HTML_LANG__");
  expect(template.documentElement.dataset.astryxTheme).toBe(eneoTheme.name);
  expect(template.querySelector("title")).toBeNull();
  expect(template.querySelector('meta[name="viewport"]')?.getAttribute("content")).toBe(
    "width=device-width, initial-scale=1, viewport-fit=cover, interactive-widget=resizes-content"
  );
  for (const [scheme, color] of Object.entries(surfaceColors())) {
    expect(
      template
        .querySelector(`meta[name="theme-color"][media="(prefers-color-scheme: ${scheme})"]`)
        ?.getAttribute("content")
    ).toBe(color);
  }
  for (const [name, content] of Object.entries({
    description: "Eneo",
    "apple-mobile-web-app-capable": "yes",
    "apple-mobile-web-app-title": "Eneo",
    "mobile-web-app-capable": "yes"
  }))
    expect(template.querySelector(`meta[name="${name}"]`)?.getAttribute("content")).toBe(content);
  expect(template.querySelector('link[rel="icon"]')?.getAttribute("href")).toBe("/favicon.ico");
  expect(template.querySelector('link[rel="manifest"]')?.getAttribute("href")).toBe(
    "/manifest.json"
  );
  expect(template.querySelector('link[rel="preload"][as="font"]')?.getAttribute("href")).toBe(
    "/src/assets/fonts/figtree-latin-wght-normal.woff2"
  );
  expect(
    template.querySelector("[data-astryx-chat-following-style]")?.textContent?.replace(/\s/g, "")
  ).toBe("[data-astryx-chat-following]{overflow-anchor:none!important;}");
  const inline = template.querySelectorAll<HTMLScriptElement | HTMLStyleElement>(
    "script:not([src]), style"
  );
  expect(inline).toHaveLength(2);
  for (const element of inline) expect(element.nonce).toBe("__ENEO_CSP_NONCE__");
  expect([...new Set(html.match(/__ENEO_[A-Z_]+__/g))].sort()).toEqual([
    "__ENEO_CSP_NONCE__",
    "__ENEO_HTML_LANG__"
  ]);
});

it.each([
  ["dark", false, "dark"],
  ["light", true, "light"],
  ["system", true, "dark"],
  ["system", false, "light"],
  [null, true, "dark"],
  ["unknown", false, "light"],
  ["blocked", true, "dark"]
])("sets the pre-paint theme for storage %s and system dark %s", (stored, dark, expected) => {
  if (stored) localStorage.setItem("theme", stored);
  if (stored === "blocked")
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("Storage blocked");
    });
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue({ matches: dark }));
  document.documentElement.className = "antialiased light dark";
  const source = template.querySelector("script:not([src])")?.textContent;
  expect(source).toBeTruthy();
  runInNewContext(source!, { document, localStorage, matchMedia });
  expect(document.documentElement.classList.contains(expected)).toBe(true);
  expect(document.documentElement.classList.contains(expected === "dark" ? "light" : "dark")).toBe(
    false
  );
  expect(document.documentElement.classList.contains("antialiased")).toBe(true);
  expect(document.documentElement.dataset.theme).toBe(expected);
  expect(document.documentElement.style.colorScheme).toBe(expected);
});
