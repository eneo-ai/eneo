import { isLocale, LOCALE_COOKIE, type Locale } from "./locales";

export function writeLocaleCookie(locale: Locale, doc: Document = document): void {
  doc.cookie = `${LOCALE_COOKIE}=${locale}; Path=/; Max-Age=31536000; SameSite=Lax${
    doc.location.protocol === "https:" ? "; Secure" : ""
  }`;
}

/** Boot data, router titles and React must all read the same document language. */
export function switchLocale(locale: string): void {
  if (!isLocale(locale)) return;
  writeLocaleCookie(locale);
  window.location.reload();
}
