import type { Metadata } from "next";
import { unstable_rethrow } from "next/navigation";
import { getTranslations } from "next-intl/server";

type Translator = Awaited<ReturnType<typeof getTranslations>>;

/**
 * The tab title of a page below a space tab (a collection, an app, an
 * editor): the resource's name, so every page has its own title (WCAG 2.4.2).
 * The space layout's template adds the space: "Upphandlingspolicy ·
 * Upphandling · Eneo". When the name cannot be loaded (the page itself then
 * shows the 404 or error), the title falls back to the tab's name.
 *
 * @example
 * export async function generateMetadata({ params }) {
 *   const { appId } = await params;
 *   return spacePageTitle(async () => (await loadApp(appId)).name, "apps");
 * }
 */
export async function spacePageTitle(
  load: (t: Translator) => Promise<string>,
  fallbackKey: string
): Promise<Metadata> {
  const t = await getTranslations();
  try {
    return { title: await load(t) };
  } catch (error) {
    // Redirects (an expired session) and other Next.js control flow go through.
    unstable_rethrow(error);
    return { title: t(fallbackKey) };
  }
}
