export function readUserQuery(url: URL) {
  const params = url.searchParams;
  const requestedPage = Number(params.get("page") || "1");
  return {
    tab: params.get("tab") === "inactive" ? ("inactive" as const) : ("active" as const),
    search: (params.get("search") || params.get("search_email") || "").trim(),
    searchName: (params.get("search_name") || "").trim(),
    roleId: params.get("role_id") || "",
    page: Number.isInteger(requestedPage) ? Math.min(100, Math.max(1, requestedPage)) : 1
  };
}

export type UserQuery = ReturnType<typeof readUserQuery>;

/** Status and filter changes start on page one; page links retain every filter. */
export function userQueryString(query: UserQuery, change: Partial<UserQuery> = {}) {
  const next = { ...query, page: 1, ...change };
  const params = new URLSearchParams({ tab: next.tab });
  if (next.search) params.set("search", next.search);
  if (next.searchName) params.set("search_name", next.searchName);
  if (next.roleId) params.set("role_id", next.roleId);
  if (next.page > 1) params.set("page", String(next.page));
  return `?${params}`;
}
