import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

/**
 * `export const generateMetadata = pageTitle("dashboard")` → the tab shows
 * "Dashboard · Eneo" (the root layout supplies the " · Eneo" template). Set on
 * area layouts so child pages inherit the area title without per-page wiring.
 */
export function pageTitle(key: string): () => Promise<Metadata> {
  return async () => {
    const t = await getTranslations();
    return { title: t(key) };
  };
}
