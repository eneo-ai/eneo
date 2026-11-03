import type { RouterContext } from "@/router";
import type { Schema } from "./api/models";

/**
 * Document titles of the Vite build: `head` on a route sets `<title>` through
 * `HeadContent` in the root route; the deepest route with a title wins.
 * Without one the tab shows "Eneo"; with one, "<Page> · Eneo", as the Next
 * root layout's title template did.
 */
const APP_TITLE = "Eneo";

/** The root route's `head`: the title of a route that sets none. */
export const rootHead = () => title();

/** Compose one document title, omitting parts unavailable during a failed load. */
export function title(...parts: (string | undefined)[]) {
  return { meta: [{ title: [...parts.filter(Boolean), APP_TITLE].join(" · ") }] };
}

/**
 * A route's `head` titled by the message `key`.
 *
 * @example createFileRoute("/login")({ head: routeTitle("login"), … }) // "Logga in · Eneo"
 */
export function routeTitle(key: string) {
  return ({ match }: { match: { context: Pick<RouterContext, "t"> } }) =>
    title(match.context.t(key));
}

type SpaceNameData = Pick<Schema<"SpacePublic">, "name" | "personal" | "organization">;
type TitleMatch = { routeId: string; loaderData?: unknown };

export function spaceName(space: SpaceNameData, t: RouterContext["t"]): string {
  return space.personal ? t("personal") : space.organization ? t("organization") : space.name;
}

/** The space layout returns SpacePublic; other matches have unrelated loader data. */
export function spaceTitle(matches: readonly TitleMatch[], t: RouterContext["t"], page?: string) {
  const space = matches.find((match) => match.routeId === "/_app/spaces/$spaceId")?.loaderData as
    SpaceNameData | undefined;
  return title(page, space && spaceName(space, t));
}

/** A resource's own name, or its translated page name when loading failed. */
export function resourceTitle(fallbackKey: string) {
  return ({
    match,
    matches,
    loaderData
  }: {
    match: { context: Pick<RouterContext, "t"> };
    matches: readonly TitleMatch[];
    loaderData?: { name: string };
  }) => spaceTitle(matches, match.context.t, loaderData?.name ?? match.context.t(fallbackKey));
}
