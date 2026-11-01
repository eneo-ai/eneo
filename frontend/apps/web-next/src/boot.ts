import {
  defaultLocale,
  isLocale,
  LEGACY_LOCALE_COOKIE,
  LOCALE_COOKIE,
  type Locale
} from "./lib/i18n/locales";
import { writeLocaleCookie } from "./lib/i18n/switch-locale";

export { readCspNonce } from "./lib/csp-nonce";
export { loadMessages } from "./lib/i18n/locales";

export function resolveLocale(doc: Document): Locale {
  const cookies = doc.cookie.split(";").map((part) => part.trim());
  const current = cookies.find((part) => part.startsWith(`${LOCALE_COOKIE}=`));
  if (current !== undefined) {
    if (isLocale(doc.documentElement.lang)) return doc.documentElement.lang;
    const value = current.slice(LOCALE_COOKIE.length + 1);
    return isLocale(value) ? value : defaultLocale;
  }

  const legacy = cookies
    .find((part) => part.startsWith(`${LEGACY_LOCALE_COOKIE}=`))
    ?.slice(LEGACY_LOCALE_COOKIE.length + 1);
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
