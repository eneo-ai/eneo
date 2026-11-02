import {
  defaultLocale,
  isLocale,
  LEGACY_LOCALE_COOKIE,
  LOCALE_COOKIE,
  type Locale,
  RETIRED_LOCALE_COOKIE
} from "./lib/i18n/locales";
import { writeLocaleCookie } from "./lib/i18n/switch-locale";

export { readCspNonce } from "./lib/csp-nonce";
export { loadMessages } from "./lib/i18n/locales";

export function resolveLocale(doc: Document): Locale {
  const cookies = doc.cookie.split(";").map((part) => part.trim());
  const read = (name: string) =>
    cookies.find((part) => part.startsWith(`${name}=`))?.slice(name.length + 1);
  const retired = read(RETIRED_LOCALE_COOKIE);
  if (retired !== undefined) doc.cookie = `${RETIRED_LOCALE_COOKIE}=; Max-Age=0; Path=/`;
  const current = read(LOCALE_COOKIE);
  if (current !== undefined) {
    if (isLocale(doc.documentElement.lang)) return doc.documentElement.lang;
    return isLocale(current) ? current : defaultLocale;
  }

  const legacy = isLocale(retired) ? retired : read(LEGACY_LOCALE_COOKIE);
  if (isLocale(legacy)) {
    writeLocaleCookie(legacy, doc);
    return legacy;
  }
  try {
    const stored = doc.defaultView?.localStorage.getItem("language");
    if (isLocale(stored)) {
      writeLocaleCookie(stored, doc);
      return stored;
    }
  } catch {
    // Storage can be denied; the server's document language still works.
  }
  return isLocale(doc.documentElement.lang) ? doc.documentElement.lang : defaultLocale;
}

/** Works even when the locale catalogue or the React renderer cannot load. */
export function showBootError(root: HTMLElement): void {
  // HeadContent cannot supply the document title when React never starts.
  document.title = "Eneo";
  const main = document.createElement("main");
  main.style.cssText = "max-width:40rem;margin:10vh auto;padding:2rem;font-family:system-ui";
  const heading = document.createElement("h1");
  heading.lang = "sv";
  heading.textContent = "Det gick inte att starta Eneo";
  const message = document.createElement("p");
  message.lang = "en";
  message.textContent = "Eneo could not start. Please reload the page to try again.";
  const retry = document.createElement("a");
  retry.href = "";
  retry.textContent = "Försök igen / Try again";
  main.append(heading, message, retry);
  root.replaceChildren(main);
}
