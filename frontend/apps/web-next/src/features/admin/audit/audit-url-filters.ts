import type { ActionType, AuditFilters } from "./audit";

type ReadableSearchParams = Pick<URLSearchParams, "get" | "getAll">;

export const DEFAULT_AUDIT_FILTERS: AuditFilters = {
  page: 1,
  actions: [],
  search: ""
};

function parsePage(value: string | null): number {
  const page = Number(value);
  return Number.isInteger(page) && page > 1 ? page : 1;
}

function readParam(searchParams: ReadableSearchParams, key: string): string | undefined {
  const value = searchParams.get(key)?.trim();
  return value ? value : undefined;
}

function parseActions(searchParams: ReadableSearchParams): ActionType[] {
  const raw = [...searchParams.getAll("actions"), ...searchParams.getAll("action")].flatMap(
    (value) => value.split(",")
  );
  const actions = raw.map((value) => value.trim()).filter(Boolean);
  return [...new Set(actions)] as ActionType[];
}

export function parseAuditFilters(searchParams: ReadableSearchParams): AuditFilters {
  const userId = readParam(searchParams, "user_id") ?? readParam(searchParams, "userId");
  const userLabel = userId
    ? (readParam(searchParams, "user_label") ?? readParam(searchParams, "userLabel"))
    : undefined;

  return {
    page: parsePage(searchParams.get("page")),
    from_date: readParam(searchParams, "from_date"),
    to_date: readParam(searchParams, "to_date"),
    actions: userId ? [] : parseActions(searchParams),
    search: userId ? "" : (readParam(searchParams, "search") ?? ""),
    userId,
    userLabel
  };
}

export function auditFiltersSearchParams(filters: AuditFilters): URLSearchParams {
  const params = new URLSearchParams();

  if (filters.page > 1) params.set("page", String(filters.page));
  if (filters.from_date) params.set("from_date", filters.from_date);
  if (filters.to_date) params.set("to_date", filters.to_date);

  if (filters.userId) {
    params.set("user_id", filters.userId);
    if (filters.userLabel) params.set("user_label", filters.userLabel);
    return params;
  }

  const search = filters.search.trim();
  if (search) params.set("search", search);
  if (filters.actions.length > 0) params.set("actions", filters.actions.join(","));

  return params;
}
