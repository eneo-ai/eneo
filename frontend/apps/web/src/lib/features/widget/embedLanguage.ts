import type { WidgetPublicConfig } from "@eneo/eneo-js";
import { localizeUrl } from "$lib/paraglide/runtime";

/**
 * Where the embed page belongs for a widget whose language is fixed, or null
 * when the request is already there or the widget follows the host page. The
 * loader and the stand-alone link pick the language when the page is framed
 * or copied; this keeps a later change of the setting from waiting for them.
 */
export function embedLanguageRedirect(
  url: URL,
  language: WidgetPublicConfig["language"]
): string | null {
  if (language !== "sv" && language !== "en") return null;
  const localized = localizeUrl(url, { locale: language });
  return localized.href === url.href ? null : localized.pathname + localized.search;
}
