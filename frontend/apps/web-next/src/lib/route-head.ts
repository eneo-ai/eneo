import type { RouterContext } from "@/router";

/**
 * Document titles of the Vite build: `head` on a route sets `<title>` through
 * `HeadContent` in the root route; the deepest route with a title wins.
 * Without one the tab shows "Eneo"; with one, "<Page> · Eneo", as the Next
 * root layout's title template did.
 */
const APP_TITLE = "Eneo";

/** The root route's `head`: the title of a route that sets none. */
export const rootHead = () => ({ meta: [{ title: APP_TITLE }] });

/**
 * A route's `head` titled by the message `key`.
 *
 * @example createFileRoute("/login")({ head: routeTitle("login"), … }) // "Logga in · Eneo"
 */
export function routeTitle(key: string) {
  return ({ match }: { match: { context: Pick<RouterContext, "t"> } }) => ({
    meta: [{ title: `${match.context.t(key)} · ${APP_TITLE}` }]
  });
}
