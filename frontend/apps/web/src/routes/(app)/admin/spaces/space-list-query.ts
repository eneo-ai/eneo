import type { AdminSpaceListItem } from "@eneo/eneo-js";
import { ACTIVITY_RANK } from "$lib/features/spaces/oversight/activity";

export const MEMBERSHIP_FILTERS = ["all", "member", "not_member"] as const;
export const SHOW_FILTERS = ["all", "attention", "no_admin", "widget_request"] as const;
export const SORT_COLUMNS = ["name", "members", "activity"] as const;
export const PAGE_SIZE = 50;

export type MembershipFilter = (typeof MEMBERSHIP_FILTERS)[number];
export type ShowFilter = (typeof SHOW_FILTERS)[number];
export type SortColumn = (typeof SORT_COLUMNS)[number];
export type SortDirection = "asc" | "desc";

export type SpaceListQuery = {
  q: string;
  membership: MembershipFilter;
  show: ShowFilter;
  sort: SortColumn;
  dir: SortDirection;
  page: number;
};

/** Names A–Ö, the biggest spaces and the most recently used ones first. */
export const DEFAULT_DIRECTION: Record<SortColumn, SortDirection> = {
  name: "asc",
  members: "desc",
  activity: "desc"
};

export const DEFAULT_QUERY: SpaceListQuery = {
  q: "",
  membership: "all",
  show: "all",
  sort: "name",
  dir: DEFAULT_DIRECTION.name,
  page: 1
};

function oneOf<T extends string>(allowed: readonly T[], value: string | null, fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback;
}

/** The list's state from the URL; anything missing or invalid falls back to the default. */
export function readSpaceListQuery(url: URL): SpaceListQuery {
  const params = url.searchParams;
  const sort = oneOf(SORT_COLUMNS, params.get("sort"), DEFAULT_QUERY.sort);
  const page = Number(params.get("page"));
  return {
    q: params.get("q")?.trim() ?? "",
    membership: oneOf(MEMBERSHIP_FILTERS, params.get("membership"), DEFAULT_QUERY.membership),
    show: oneOf(SHOW_FILTERS, params.get("show"), DEFAULT_QUERY.show),
    sort,
    dir: oneOf(["asc", "desc"] as const, params.get("dir"), DEFAULT_DIRECTION[sort]),
    page: Number.isInteger(page) && page > 1 ? page : 1
  };
}

/**
 * The query string for `query` after `change`, leaving out every default. A
 * change goes back to page one unless it names a page itself.
 */
export function spaceListQueryString(
  query: SpaceListQuery,
  change: Partial<SpaceListQuery> = {}
): string {
  const next = { ...query, page: 1, ...change };
  const params = new URLSearchParams();
  const q = next.q.trim();
  if (q) params.set("q", q);
  if (next.membership !== DEFAULT_QUERY.membership) params.set("membership", next.membership);
  if (next.show !== DEFAULT_QUERY.show) params.set("show", next.show);
  if (next.sort !== DEFAULT_QUERY.sort) params.set("sort", next.sort);
  if (next.dir !== DEFAULT_DIRECTION[next.sort]) params.set("dir", next.dir);
  if (next.page > 1) params.set("page", String(next.page));
  const search = params.toString();
  return search ? `?${search}` : "";
}

/** Whether the search or a filter narrows the list; sorting and paging do not. */
export function isFiltered(query: SpaceListQuery): boolean {
  return (
    query.q.trim() !== "" ||
    query.membership !== DEFAULT_QUERY.membership ||
    query.show !== DEFAULT_QUERY.show
  );
}

/** Sorting by a new column starts in that column's natural direction; the same column flips. */
export function nextSort(
  query: SpaceListQuery,
  column: SortColumn
): Pick<SpaceListQuery, "sort" | "dir"> {
  if (query.sort !== column) return { sort: column, dir: DEFAULT_DIRECTION[column] };
  return { sort: column, dir: query.dir === "asc" ? "desc" : "asc" };
}

export function isMember(item: Pick<AdminSpaceListItem, "viewer_membership">): boolean {
  return item.viewer_membership.role != null;
}

function matchesSearch(item: AdminSpaceListItem, search: string): boolean {
  const needle = search.trim().toLocaleLowerCase();
  if (!needle) return true;
  return [item.name, item.description ?? "", ...item.admins.principals.map((admin) => admin.name)]
    .map((text) => text.toLocaleLowerCase())
    .some((text) => text.includes(needle));
}

function matchesShow(item: AdminSpaceListItem, show: ShowFilter): boolean {
  switch (show) {
    case "all":
      return true;
    case "attention":
      return item.attention.length > 0;
    case "no_admin":
      return item.attention.includes("no_admin");
    case "widget_request":
      return item.attention.includes("widget_activation_requested");
    default:
      return show satisfies never;
  }
}

function matchesMembership(item: AdminSpaceListItem, membership: MembershipFilter): boolean {
  switch (membership) {
    case "all":
      return true;
    case "member":
      return isMember(item);
    case "not_member":
      return !isMember(item);
    default:
      return membership satisfies never;
  }
}

/** The spaces the search and both filters let through, in the order given. */
export function filterSpaces(
  items: readonly AdminSpaceListItem[],
  query: SpaceListQuery
): AdminSpaceListItem[] {
  return items.filter(
    (item) =>
      matchesSearch(item, query.q) &&
      matchesShow(item, query.show) &&
      matchesMembership(item, query.membership)
  );
}

/**
 * How many spaces each membership option would show with the current search
 * and "Visa" filter, so the counts in the options always match the result.
 */
export function membershipCounts(
  items: readonly AdminSpaceListItem[],
  query: SpaceListQuery
): Record<MembershipFilter, number> {
  const candidates = items.filter(
    (item) => matchesSearch(item, query.q) && matchesShow(item, query.show)
  );
  const member = candidates.filter(isMember).length;
  return { all: candidates.length, member, not_member: candidates.length - member };
}

/** A sorted copy. Ties fall back to the name, so the order never jumps between renders. */
export function sortSpaces(
  items: readonly AdminSpaceListItem[],
  sort: SortColumn,
  dir: SortDirection,
  collator: Intl.Collator
): AdminSpaceListItem[] {
  const sign = dir === "asc" ? 1 : -1;
  const byName = (a: AdminSpaceListItem, b: AdminSpaceListItem) =>
    collator.compare(a.name, b.name) || a.id.localeCompare(b.id);
  return [...items].sort((a, b) => {
    switch (sort) {
      case "name":
        return sign * byName(a, b);
      case "members":
        return sign * (a.member_count - b.member_count) || byName(a, b);
      case "activity":
        return (
          sign * (ACTIVITY_RANK[a.last_activity] - ACTIVITY_RANK[b.last_activity]) || byName(a, b)
        );
      default:
        return sort satisfies never;
    }
  });
}

export function pageCount(total: number): number {
  return Math.max(1, Math.ceil(total / PAGE_SIZE));
}

/** The requested page, moved into range when the result got shorter. */
export function clampPage(page: number, total: number): number {
  return Math.min(Math.max(1, page), pageCount(total));
}
