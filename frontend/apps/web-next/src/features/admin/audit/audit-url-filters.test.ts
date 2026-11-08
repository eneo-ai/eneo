import { describe, expect, it, vi } from "vitest";
import type { EneoClient } from "@/lib/api/browser";
import type { ActionType, AuditFilters } from "./audit";
import { auditExportRequest, auditLogsQueryOptions } from "./audit";
import { auditFiltersSearchParams, parseAuditFilters, parseAuditTab } from "./audit-url-filters";

const action = (value: string) => value as ActionType;

it.each([undefined, null, "categories", "other", ["config"], {}])(
  "defaults an invalid tab %j to logs",
  (value) => {
    expect(parseAuditTab(value)).toBe("logs");
  }
);
it("accepts the configuration deep link", () => expect(parseAuditTab("config")).toBe("config"));

describe("parseAuditFilters", () => {
  it.each(["bad", "2026-99-99", "2026-02-30", "2025-02-29"])(
    "ignores an invalid calendar date: %s",
    (date) => {
      const filters = parseAuditFilters(new URLSearchParams({ from_date: date, to_date: date }));
      expect(filters.from_date).toBeUndefined();
      expect(filters.to_date).toBeUndefined();
    }
  );
  it("accepts leap days", () => {
    expect(parseAuditFilters(new URLSearchParams({ from_date: "2024-02-29" })).from_date).toBe(
      "2024-02-29"
    );
  });
  it("restores a search deep link with paging, dates, and actions", () => {
    const filters = parseAuditFilters(
      new URLSearchParams(
        "search=invoice&page=3&from_date=2026-01-01&to_date=2026-01-31&actions=login,logout&actions=login"
      )
    );

    expect(filters).toEqual({
      page: 3,
      from_date: "2026-01-01",
      to_date: "2026-01-31",
      actions: [action("login"), action("logout")],
      search: "invoice",
      userId: undefined,
      userLabel: undefined
    });
  });

  it("normalizes invalid and blank query params to default filters", () => {
    const filters = parseAuditFilters(
      new URLSearchParams("search=%20&page=-2&from_date=%20&to_date=&actions=,,")
    );

    expect(filters).toEqual({
      page: 1,
      from_date: undefined,
      to_date: undefined,
      actions: [],
      search: "",
      userId: undefined,
      userLabel: undefined
    });
  });

  it("keeps action and text filters together with a selected actor", () => {
    const filters = parseAuditFilters(
      new URLSearchParams(
        "user_id=user-1&user_label=user%40example.com&search=invoice&actions=login&page=2"
      )
    );

    expect(filters).toEqual({
      page: 2,
      from_date: undefined,
      to_date: undefined,
      actions: [action("login")],
      search: "invoice",
      userId: "user-1",
      userLabel: "user@example.com"
    });
  });
});

describe("auditExportRequest", () => {
  it("serializes the date range and one selected action for regular exports", () => {
    const body = auditExportRequest(
      {
        page: 1,
        from_date: "2026-01-01",
        to_date: "2026-01-31",
        actions: [action("login")],
        search: "ignored",
        userId: undefined,
        userLabel: undefined
      },
      "csv"
    );

    expect(body).toEqual({
      from_date: "2026-01-01",
      to_date: "2026-01-31",
      actor_id: undefined,
      action: "login",
      format: "csv"
    });
  });

  it("exports the selected actor and action without broadening to GDPR subject events", () => {
    const body = auditExportRequest(
      {
        page: 1,
        from_date: "2026-01-01",
        to_date: "2026-01-31",
        actions: [action("login")],
        search: "ignored",
        userId: "user-1",
        userLabel: "user@example.com"
      },
      "jsonl"
    );

    expect(body).not.toHaveProperty("user_id");
    expect(body).toEqual({
      from_date: "2026-01-01",
      to_date: "2026-01-31",
      actor_id: "user-1",
      action: "login",
      format: "jsonl"
    });
  });
});

describe("auditFiltersSearchParams", () => {
  it("omits default filters and serializes only active filters", () => {
    const filters: AuditFilters = {
      page: 2,
      from_date: "2026-01-01",
      to_date: "2026-01-31",
      actions: [action("login"), action("logout")],
      search: " invoice ",
      userId: undefined,
      userLabel: undefined
    };

    const params = auditFiltersSearchParams(filters);

    expect(params.get("page")).toBe("2");
    expect(params.get("from_date")).toBe("2026-01-01");
    expect(params.get("to_date")).toBe("2026-01-31");
    expect(params.get("search")).toBe("invoice");
    expect(params.get("actions")).toBe("login,logout");
  });

  it("serializes action and search filters together with the actor", () => {
    const filters: AuditFilters = {
      page: 1,
      actions: [action("login")],
      search: "ignored",
      userId: "user-1",
      userLabel: "user@example.com"
    };

    const params = auditFiltersSearchParams(filters);

    expect(params.get("user_id")).toBe("user-1");
    expect(params.get("user_label")).toBe("user@example.com");
    expect(params.get("search")).toBe("ignored");
    expect(params.get("actions")).toBe("login");
  });
});

describe("auditLogsQueryOptions", () => {
  it("requests the ordinary logs endpoint with all filters and actor_id", async () => {
    const GET = vi.fn().mockResolvedValue({ data: { logs: [] }, response: new Response() });
    const filters: AuditFilters = {
      page: 1,
      actions: ["user_created"],
      search: " invoice ",
      userId: "user-1",
      from_date: "2026-01-01",
      to_date: "2026-01-31"
    };
    const options = auditLogsQueryOptions({ GET } as unknown as EneoClient, filters);
    await options.queryFn!({} as never);
    expect(GET).toHaveBeenCalledWith("/api/v1/audit/logs", {
      params: {
        query: {
          page: 1,
          page_size: 100,
          actor_id: "user-1",
          actions: ["user_created"],
          search: "invoice",
          from_date: "2026-01-01",
          to_date: "2026-01-31"
        }
      }
    });
  });
  it("keys on the trimmed search, so trailing whitespace reuses the cached logs", () => {
    const api = {} as EneoClient;
    const filters: AuditFilters = { page: 1, actions: [], search: "abc" };
    expect(auditLogsQueryOptions(api, { ...filters, search: "abc " }).queryKey).toEqual(
      auditLogsQueryOptions(api, filters).queryKey
    );
  });
});
