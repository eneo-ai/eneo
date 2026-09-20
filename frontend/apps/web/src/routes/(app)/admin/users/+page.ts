import { error, redirect } from "@sveltejs/kit";
import { m } from "$lib/paraglide/messages";
import { normalizeLocalPasswordCapability } from "$lib/features/auth/passwordChange";
import { readUserQuery, userQueryString } from "./user-query";
import type { PageLoad } from "./$types";

export const load: PageLoad = async (event) => {
  const { eneo } = await event.parent();
  event.depends("admin:users");
  const query = readUserQuery(event.url);
  if ([query.search, query.searchName].some((value) => value.length > 0 && value.length < 3)) {
    error(400, { status: 400, code: 0, message: m.admin_users_search_hint() });
  }

  const [response, passwordPolicy] = await Promise.all([
    eneo.users.list({
      includeDetails: true,
      search_email: query.search || undefined,
      search_name: query.searchName || undefined,
      role_id: query.roleId || undefined,
      state_filter: query.tab,
      page: query.page
    }),
    eneo.users.passwordPolicy()
  ]);
  const passwordCapability = normalizeLocalPasswordCapability(passwordPolicy);
  if (passwordCapability.source !== "eneo") {
    error(503, { status: 503, code: 0, message: m.password_policy_unavailable() });
  }

  // Deactivating/deleting the last row on a page can shorten the result set.
  const lastPage = Math.max(1, response.metadata.total_pages);
  if (query.page > lastPage) {
    redirect(307, event.url.pathname + userQueryString(query, { page: lastPage }));
  }

  return {
    passwordCapability,
    query,
    users: response.items,
    pagination: response.metadata,
    counts: response.metadata.counts
  };
};
