import { afterEach, expect, it, vi } from "vitest";
import { switchLocale, writeLocaleCookie } from "./switch-locale";

afterEach(() => vi.unstubAllGlobals());

it.each(["https:", "http:"])(
  "persists the language and reloads the whole document on %s",
  (protocol) => {
    const reload = vi.fn();
    vi.stubGlobal("document", { cookie: "", location: { protocol } });
    vi.stubGlobal("window", { location: { protocol, reload } });
    switchLocale("en");
    expect(document.cookie).toBe(
      "NEXT_LOCALE=en; Path=/; Max-Age=31536000; SameSite=Lax" +
        (protocol === "https:" ? "; Secure" : "")
    );
    expect(reload).toHaveBeenCalledOnce();
  }
);

it("rejects an unsupported language without changing the cookie or document", () => {
  const reload = vi.fn();
  vi.stubGlobal("document", { cookie: "NEXT_LOCALE=sv" });
  vi.stubGlobal("window", { location: { protocol: "https:", reload } });
  switchLocale("de");
  expect(document.cookie).toBe("NEXT_LOCALE=sv");
  expect(reload).not.toHaveBeenCalled();
});

it("can persist a migrated choice without reloading the document", () => {
  const reload = vi.fn();
  vi.stubGlobal("document", { cookie: "", location: { protocol: "https:" } });
  vi.stubGlobal("window", { location: { protocol: "https:", reload } });

  writeLocaleCookie("en");
  expect(document.cookie).toBe("NEXT_LOCALE=en; Path=/; Max-Age=31536000; SameSite=Lax; Secure");
  expect(reload).not.toHaveBeenCalled();
});
