import { redirect } from "@sveltejs/kit";
import { localizeHref } from "$lib/paraglide/runtime";
import type { PageLoad } from "./$types";

// Preserve bookmarked and previously shared release-note URLs.
export const load: PageLoad = ({ url }) => {
  redirect(308, localizeHref("/news") + url.search + url.hash);
};
