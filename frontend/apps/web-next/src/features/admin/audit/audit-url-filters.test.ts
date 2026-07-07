import { describe, expect, it } from "vitest";
import type { ActionType, AuditFilters } from "./audit";
import { auditExportRequest } from "./audit";
import { auditFiltersSearchParams, parseAuditFilters } from "./audit-url-filters";

const action = (value: string) => value as ActionType;

describe("parseAuditFilters", () => {
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

  it("keeps the user endpoint filter canonical when a user is selected", () => {
    const filters = parseAuditFilters(
      new URLSearchParams(
        "user_id=user-1&user_label=user%40example.com&search=ignored&actions=login&page=2"
      )
    );

    expect(filters).toEqual({
      page: 2,
      from_date: undefined,
      to_date: undefined,
      actions: [],
      search: "",
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
      user_id: undefined,
      action: "login",
      format: "csv"
    });
  });

  it("uses the GDPR user export filter and omits action filters for user views", () => {
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

    expect(body).toEqual({
      from_date: "2026-01-01",
      to_date: "2026-01-31",
      user_id: "user-1",
      action: undefined,
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

  it("omits action and search filters for a user-specific log view", () => {
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
    expect(params.has("search")).toBe(false);
    expect(params.has("actions")).toBe(false);
  });
});
