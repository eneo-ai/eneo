import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";
import { cache } from "react";
import { EmbedPage } from "../components/embed-page";
import { embedLanguageRedirect, embedLocale } from "../embed-language";
import { PREVIEW_QUERY } from "../preview";
import { parseScheme } from "./embed-policy";
import { fetchPublicConfig } from "./public-config";
import type { Locale } from "@/lib/i18n/locales";

/**
 * The embed page, `/embed/<id>` and `/en/embed/<id>`: the chat a visitor
 * sees inside the loader's iframe or on the stand-alone page. Its response
 * headers (where it may be framed, its language and scheme) are decided in
 * src/proxy.ts; this loads what it shows.
 */

type Query = Record<string, string | string[] | undefined>;

export type EmbedRouteProps = {
  params: Promise<{ publicId: string }>;
  searchParams: Promise<Query>;
};

// Once per request: the page and its metadata share the one fetch.
const loadConfig = cache((publicId: string) => fetchPublicConfig(publicId, { timeoutMs: 8000 }));

function single(query: Query, key: string): string | null {
  const value = query[key];
  return typeof value === "string" ? value : null;
}

/** Only a syntactically valid origin may become the postMessage peer. */
export function parseHostOrigin(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const url = new URL(raw);
    return url.origin === raw ? url.origin : null;
  } catch {
    return null;
  }
}

export async function embedMetadata(
  { params, searchParams }: EmbedRouteProps,
  pathLocale: Locale
): Promise<Metadata> {
  const { publicId } = await params;
  const query = await searchParams;
  const t = await getTranslations({ locale: pathLocale });
  let title = t("widget_preview_title");
  if (single(query, PREVIEW_QUERY) !== "1") {
    try {
      const config = await loadConfig(publicId);
      title = config ? config.texts.title || config.name : t("widget_not_available_title");
    } catch {
      title = t("widget_not_available_title");
    }
  }
  return { title: { absolute: title }, robots: { index: false, follow: false } };
}

export async function EmbedRoute({
  params,
  searchParams,
  pathLocale
}: EmbedRouteProps & { pathLocale: Locale }) {
  const { publicId } = await params;
  const query = await searchParams;
  const standalone = single(query, "mode") === "full";
  // The admin page's live preview: the token is in the fragment, so the
  // configuration is fetched in the browser.
  const preview = single(query, PREVIEW_QUERY) === "1";

  // A paused, archived or unknown widget. The page still renders, as a
  // notice, because the loader on the host site cannot tell a refused frame
  // from a slow one and would otherwise open a blank panel. Any other
  // failure reaches error.tsx.
  const config = preview ? null : await loadConfig(publicId);
  const unavailable = !preview && config === null;

  // A fixed language wins over the one the loader or a copied link asked for.
  if (config) {
    const search = new URLSearchParams(
      Object.entries(query).flatMap(([key, value]) =>
        typeof value === "string" ? [[key, value]] : (value ?? []).map((item) => [key, item])
      )
    ).toString();
    const localized = embedLanguageRedirect(
      pathLocale,
      embedLocale(pathLocale, config.language),
      publicId,
      search ? `?${search}` : ""
    );
    if (localized) redirect(localized);
  }

  return (
    <EmbedPage
      config={config}
      unavailable={unavailable}
      publicId={publicId}
      hostOrigin={standalone ? null : parseHostOrigin(single(query, "origin"))}
      hostScheme={parseScheme(single(query, "scheme"))}
      preview={preview}
    />
  );
}
