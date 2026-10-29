import { isLocale, LOCALE_COOKIE } from "./locales";

/** Boot data, router titles and React must all read the same document language. */
export function switchLocale(locale: string): void {
  if (!isLocale(locale)) return;
  document.cookie = `${LOCALE_COOKIE}=${locale}; Path=/; Max-Age=31536000; SameSite=Lax${
    window.location.protocol === "https:" ? "; Secure" : ""
  }`;
  window.location.reload();
}
