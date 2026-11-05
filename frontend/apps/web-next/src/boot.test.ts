// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { readCspNonce, resolveLocale, showBootError } from "./boot";

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.lang = "";
  document.cookie = "eneo_locale=; Max-Age=0; Path=/";
  document.cookie = "NEXT_LOCALE=; Max-Age=0; Path=/";
  document.cookie = "PARAGLIDE_LOCALE=; Max-Age=0; Path=/";
  window.localStorage.removeItem("language");
  document.head.querySelectorAll('meta[property="csp-nonce"]').forEach((meta) => meta.remove());
});

it.each(["sv", "de", ""])(
  "never imports legacy preferences while current cookie %s is present",
  (current) => {
    document.documentElement.lang = "sv";
    document.cookie = `eneo_locale=${current}; Path=/`;
    document.cookie = "PARAGLIDE_LOCALE=en; Path=/";
    window.localStorage.setItem("language", "en");
    const readStorage = vi.spyOn(Storage.prototype, "getItem");

    expect(resolveLocale(document)).toBe("sv");
    expect(readStorage).not.toHaveBeenCalled();
    expect(document.cookie).toContain(`eneo_locale=${current}`);
  }
);

it("migrates a valid legacy cookie ahead of storage without modifying legacy choices", () => {
  document.documentElement.lang = "sv";
  document.cookie = "PARAGLIDE_LOCALE=en; Path=/";
  window.localStorage.setItem("language", "sv");
  const readStorage = vi.spyOn(Storage.prototype, "getItem");

  expect(resolveLocale(document)).toBe("en");
  expect(document.cookie).toContain("eneo_locale=en");
  expect(document.cookie).toContain("PARAGLIDE_LOCALE=en");
  expect(readStorage).not.toHaveBeenCalled();
  expect(window.localStorage.getItem("language")).toBe("sv");
});

it("adopts the cookie's earlier name ahead of the other legacy choices, then clears it", () => {
  document.documentElement.lang = "sv";
  document.cookie = "NEXT_LOCALE=en; Path=/";
  document.cookie = "PARAGLIDE_LOCALE=sv; Path=/";
  window.localStorage.setItem("language", "sv");

  expect(resolveLocale(document)).toBe("en");
  expect(document.cookie).toContain("eneo_locale=en");
  expect(document.cookie).not.toContain("NEXT_LOCALE=");
  expect(document.cookie).toContain("PARAGLIDE_LOCALE=sv");
});

it.each(["de", ""])("clears an invalid earlier cookie %s and keeps looking", (retired) => {
  document.documentElement.lang = "sv";
  document.cookie = `NEXT_LOCALE=${retired}; Path=/`;
  document.cookie = "PARAGLIDE_LOCALE=en; Path=/";

  expect(resolveLocale(document)).toBe("en");
  expect(document.cookie).toContain("eneo_locale=en");
  expect(document.cookie).not.toContain("NEXT_LOCALE=");
});

it("clears the earlier cookie while the current one decides", () => {
  document.documentElement.lang = "sv";
  document.cookie = "eneo_locale=sv; Path=/";
  document.cookie = "NEXT_LOCALE=en; Path=/";

  expect(resolveLocale(document)).toBe("sv");
  expect(document.cookie).not.toContain("NEXT_LOCALE=");
});

it("imports a valid stored language only without an eligible cookie", () => {
  document.documentElement.lang = "sv";
  document.cookie = "PARAGLIDE_LOCALE=de; Path=/";
  window.localStorage.setItem("language", "en");

  expect(resolveLocale(document)).toBe("en");
  expect(document.cookie).toContain("eneo_locale=en");
  expect(document.cookie).toContain("PARAGLIDE_LOCALE=de");
  expect(window.localStorage.getItem("language")).toBe("en");
});

it("ignores invalid or denied legacy storage without setting a current cookie", () => {
  document.documentElement.lang = "sv";
  window.localStorage.setItem("language", "de");
  expect(resolveLocale(document)).toBe("sv");
  expect(document.cookie).not.toContain("eneo_locale=");

  vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
    throw new DOMException("Storage denied", "SecurityError");
  });
  expect(resolveLocale(document)).toBe("sv");
  expect(document.cookie).not.toContain("eneo_locale=");
});

it.each([
  ["en", "sv", "en"],
  ["sv", "en", "sv"],
  ["__ENEO_HTML_LANG__", "en", "en"],
  ["__ENEO_HTML_LANG__", "de", "sv"],
  ["", "", "sv"]
])("resolves html language %s and cookie %s to %s", (html, cookie, expected) => {
  document.documentElement.lang = html;
  document.cookie = `eneo_locale=${cookie}; Path=/`;
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

it.each(["/embed/widget-id", "/en/embed/widget-id"])(
  "uses the embed document's language without reading or migrating preferences at %s",
  (path) => {
    window.history.replaceState({}, "", path);
    document.documentElement.lang = "sv";
    document.cookie = "NEXT_LOCALE=en; Path=/";
    const readCookie = vi.spyOn(document, "cookie", "get");
    const writeCookie = vi.spyOn(document, "cookie", "set");
    const storage = vi.spyOn(Storage.prototype, "getItem");
    expect(resolveLocale(document)).toBe("sv");
    expect(readCookie).not.toHaveBeenCalled();
    expect(writeCookie).not.toHaveBeenCalled();
    expect(storage).not.toHaveBeenCalled();
    window.history.replaceState({}, "", "/");
  }
);
