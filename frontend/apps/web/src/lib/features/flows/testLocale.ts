import { getLocale, overwriteGetLocale, type Locale } from "$lib/paraglide/runtime";

/**
 * Pin the locale for a test and return the restore function.
 *
 * `setLocale()` is not enough here. The compiled strategy is
 * `["url", "cookie", "baseLocale"]`, so the URL is consulted first, and under
 * jsdom that resolves to the base locale as soon as `window.location` is a
 * real URL. The cookie `setLocale()` writes never gets a vote, which is why a
 * locale-switching test passes alone and fails the moment a sibling file runs
 * beside it. Overwriting the resolver removes the strategy from the question.
 */
export function withLocale(locale: Locale): () => void {
  const previous = getLocale();
  overwriteGetLocale(() => locale);
  return () => overwriteGetLocale(() => previous);
}
