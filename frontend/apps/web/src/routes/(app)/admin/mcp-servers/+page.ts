import { redirect } from "@sveltejs/kit";
import { localizeHref } from "$lib/paraglide/runtime";
import type { PageLoad } from "./$types";
export const load: PageLoad = () => {
  redirect(307, localizeHref("/admin/tools?tab=mcp-servers"));
};
