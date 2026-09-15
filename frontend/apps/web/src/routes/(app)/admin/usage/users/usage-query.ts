import type { UserSortBy } from "@eneo/eneo-js";

const sortFields: UserSortBy[] = [
  "username",
  "input_tokens",
  "output_tokens",
  "total_tokens",
  "requests"
];

export function readUserUsageQuery(url: URL) {
  const requestedPage = Number(url.searchParams.get("page") || "1");
  const sortBy =
    sortFields.find((field) => field === url.searchParams.get("sortBy")) ?? "total_tokens";
  return {
    page: Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1,
    perPage: 25,
    sortBy,
    sortOrder: url.searchParams.get("sortOrder") === "asc" ? ("asc" as const) : ("desc" as const),
    search: (url.searchParams.get("userSearch") || "").trim()
  };
}

export function userUsageUrl(url: URL, change: Partial<ReturnType<typeof readUserUsageQuery>>) {
  const next = new URL(url);
  const state = { ...readUserUsageQuery(url), page: 1, ...change };
  next.searchParams.set("tab", "tokens");
  if (state.page > 1) next.searchParams.set("page", String(state.page));
  else next.searchParams.delete("page");
  if (state.search.trim()) next.searchParams.set("userSearch", state.search.trim());
  else next.searchParams.delete("userSearch");
  next.searchParams.set("sortBy", state.sortBy);
  next.searchParams.set("sortOrder", state.sortOrder);
  return next;
}
