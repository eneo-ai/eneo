// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { readCspNonce, resolveLocale, showBootError } from "./boot";

afterEach(() => {
  document.documentElement.lang = "";
  document.cookie = "NEXT_LOCALE=; Max-Age=0; Path=/";
  document.head.querySelectorAll('meta[property="csp-nonce"]').forEach((meta) => meta.remove());
});

it.each([
  ["en", "sv", "en"],
  ["sv", "en", "sv"],
  ["__ENEO_HTML_LANG__", "en", "en"],
  ["__ENEO_HTML_LANG__", "de", "sv"],
  ["", "", "sv"]
])("resolves html language %s and cookie %s to %s", (html, cookie, expected) => {
  document.documentElement.lang = html;
  document.cookie = `NEXT_LOCALE=${cookie}; Path=/`;
  expect(resolveLocale(document)).toBe(expected);
});

it("reads the nonce through its DOM property, including when the attribute is hidden", () => {
  expect(readCspNonce()).toBeUndefined();
  const meta = document.createElement("meta");
  meta.setAttribute("property", "csp-nonce");
  meta.nonce = "request-nonce";
  const getAttribute = meta.getAttribute.bind(meta);
  meta.getAttribute = (name) => (name === "nonce" ? "" : getAttribute(name));
  document.head.append(meta);
  expect(readCspNonce()).toBe("request-nonce");
});

it("replaces a failed boot with static text in both languages and a reload link", () => {
  const root = document.createElement("div");
  root.textContent = "Stale content";
  showBootError(root);
  expect(document.title).toBe("Eneo");
  expect(root.querySelector('h1[lang="sv"]')?.textContent).toBe("Det gick inte att starta Eneo");
  expect(root.querySelector('p[lang="en"]')?.textContent).toContain("Eneo could not start");
  expect(root.querySelector("a")?.getAttribute("href")).toBe("");
  expect(root.textContent).not.toContain("Stale content");
  expect(root.querySelector("script")).toBeNull();
});
