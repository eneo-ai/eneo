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

/**
 * The space layout's title: the space's name (the localized alias for the
 * personal and organization spaces) and the template that pages below it put
 * their own title in front of: "Kunskap · Upphandling · Eneo". When the space
 * cannot be loaded (the layout then shows the 404 or error), the root title
 * stays; redirects (an expired session) go through.
 */
export async function spaceLayoutTitle(
  load: () => Promise<{ name: string; personal: boolean; organization: boolean }>
): Promise<Metadata> {
  const t = await getTranslations();
  try {
    const space = await load();
    const name = space.personal
      ? t("personal")
      : space.organization
        ? t("organization")
        : space.name;
    return { title: { default: name, template: `%s · ${name} · Eneo` } };
  } catch (error) {
    unstable_rethrow(error);
    return {};
  }
}
