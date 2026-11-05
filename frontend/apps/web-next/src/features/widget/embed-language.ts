import type { Locale } from "@/lib/i18n/locales";

/**
 * The embed page is served at `/embed/<id>` in Swedish and `/en/embed/<id>`
 * in English, the paths the loader and copied links build (this app has no
 * locale routing otherwise; the visitor's cookie must not decide the
 * language of someone else's site). A language fixed in the widget's
 * settings wins over the path; the page redirects to the matching path so a
 * later change of the setting does not wait for the loader to notice.
 */
export function embedLocale(pathLocale: Locale, language: "sv" | "en" | "auto"): Locale {
  return language === "sv" || language === "en" ? language : pathLocale;
}

/** The path to serve `locale` at, or null when the request is already there. */
export function embedLanguageRedirect(
  pathLocale: Locale,
  locale: Locale,
  publicId: string,
  search: string
): string | null {
  if (pathLocale === locale) return null;
  const prefix = locale === "en" ? "/en" : "";
  return `${prefix}/embed/${encodeURIComponent(publicId)}${search}`;
}
