import { defaultLocale, isLocale, LOCALE_COOKIE, type Locale } from "./lib/i18n/locales";

export { readCspNonce } from "./lib/csp-nonce";
export { loadMessages } from "./lib/i18n/locales";

export function resolveLocale(doc: Document): Locale {
  if (isLocale(doc.documentElement.lang)) return doc.documentElement.lang;
  const cookie = doc.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${LOCALE_COOKIE}=`));
  const value = cookie?.slice(LOCALE_COOKIE.length + 1);
  return isLocale(value) ? value : defaultLocale;
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
