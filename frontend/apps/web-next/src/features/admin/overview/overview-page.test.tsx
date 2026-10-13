// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));

import { AdminOverviewPage } from "./overview-page";

const USERS = {
  items: [],
  metadata: {
    page: 1,
    page_size: 100,
    total_count: 42,
    total_pages: 1,
    has_next: false,
    has_previous: false,
    counts: { active: 42, inactive: 3 }
  }
};

const USAGE = {
  start_date: "2026-09-02T00:00:00Z",
  end_date: "2026-10-02T00:00:00Z",
  models: [
    { model_id: "m1", model_nickname: "Claude", input_token_usage: 1000, output_token_usage: 500 },
    { model_id: "m2", model_nickname: "GPT", input_token_usage: 200, output_token_usage: 300 }
  ],
  total_input_token_usage: 1200,
  total_output_token_usage: 800,
  total_token_usage: 2000
};

const CRAWLER = {
  as_of: "2026-10-02T10:00:00Z",
  summary: { ongoing: 1, queued: 2, issues: 4 },
  calendar: { days: [] },
  items: [],
  next_cursor: null,
  scheduler: {
    status: "ok",
    ran_at: "2026-10-02T09:00:00Z",
    stale_after_minutes: 65,
    due: 1,
    admitted: 1,
    failed: 0
  }
};

const AUDIT = {
  logs: [
    {
      id: "log-1",
      tenant_id: "tenant-1",
      actor_id: "user-1",
      actor_type: "user",
      action: "password_changed",
      entity_type: "user",
      entity_id: "user-1",
      timestamp: "2026-10-02T08:00:00Z",
      description: "Anna Lind bytte lösenord"
    }
  ],
  total_count: 1,
  page: 1,
  page_size: 5,
  total_pages: 1
};

type Responses = Record<string, unknown | (() => Promise<unknown>)>;

const ok = (data: unknown) => ({ data, error: undefined, response: new Response("{}") });
const failure = (status: number) => ({
  data: undefined,
  error: { message: "nope" },
  response: new Response("{}", { status })
});

function answer(responses: Responses) {
  api.GET.mockImplementation((path: string) => {
    const response = responses[path];
    if (response === undefined) throw new Error(`Unexpected request: ${path}`);
    return typeof response === "function" ? response() : Promise.resolve(response);
  });
}

const ALL_OK: Responses = {
  "/api/v1/admin/users/": ok(USERS),
  "/api/v1/token-usage/": ok(USAGE),
  "/api/v1/admin/crawler/": ok(CRAWLER),
  "/api/v1/audit/logs": ok(AUDIT)
};

function renderOverview({ auditLogging = true } = {}) {
  return renderInApp(<AdminOverviewPage />, {
    appContext: testAppContext({
      permissions: ["admin"],
      settings: { audit_logging_enabled: auditLogging }
    })
  });
}

const region = (name: string | RegExp) => screen.getByRole("region", { name });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AdminOverviewPage", () => {
  it("shows one linked card per area once the data is in", async () => {
    answer(ALL_OK);
    const { container } = renderOverview();
    expect(screen.getByRole("heading", { level: 1, name: "Översikt" })).toBeTruthy();

    const users = region("Aktiva användare");
    expect(await within(users).findByText("42")).toBeTruthy();
    expect(within(users).getByText("3 inaktiva konton")).toBeTruthy();
    expect(within(users).getByRole("link", { name: "Visa användare" }).getAttribute("href")).toBe(
      "/admin/users"
    );

    const usage = region("Tokenanvändning senaste 30 dagarna");
    expect(await within(usage).findByText(/^2\s?000$/)).toBeTruthy();
    expect(within(usage).getByText("2 modeller använda")).toBeTruthy();
    expect(within(usage).getByRole("link", { name: "Visa användning" }).getAttribute("href")).toBe(
      "/admin/usage"
    );

    const crawler = region("Crawler");
    expect(await within(crawler).findByText("I kö")).toBeTruthy();
    expect(within(crawler).getByText("Pågående").nextElementSibling?.textContent).toBe("1");
    expect(within(crawler).getByText("Fel och varningar").nextElementSibling?.textContent).toBe(
      "4"
    );
    expect(within(crawler).getByText("Fungerar")).toBeTruthy();
    expect(within(crawler).getByRole("link", { name: "Visa crawler" }).getAttribute("href")).toBe(
      "/admin/crawler"
    );

    const audit = region("Senaste granskningshändelser");
    expect(await within(audit).findByText("Anna Lind bytte lösenord")).toBeTruthy();
    expect(within(audit).getByText("Lösenord ändrat")).toBeTruthy();
    expect(within(audit).getByRole("list").children).toHaveLength(1);
    expect(
      within(audit).getByRole("link", { name: "Visa granskningsloggar" }).getAttribute("href")
    ).toBe("/admin/audit-logs");

    // Nothing is left loading.
    expect(document.querySelector('[aria-busy="true"]')).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("leaves the audit card out while audit logging is off", async () => {
    answer(ALL_OK);
    renderOverview({ auditLogging: false });
    expect(await within(region("Aktiva användare")).findByText("42")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Senaste granskningshändelser" })).toBeNull();
    expect(api.GET).not.toHaveBeenCalledWith("/api/v1/audit/logs", expect.anything());
  });

  it("fails one card at a time, with a retry that keeps focus and recovers", async () => {
    let attempts = 0;
    answer({
      ...ALL_OK,
      "/api/v1/admin/users/": () => {
        attempts += 1;
        return attempts === 1 ? Promise.reject(new Error("offline")) : Promise.resolve(ok(USERS));
      }
    });
    const { container } = renderOverview();

    const users = region("Aktiva användare");
    expect(await within(users).findByText("Innehållet kunde inte hämtas")).toBeTruthy();
    expect(within(users).queryByRole("status", { busy: true })).toBeNull();
    // The other cards are unaffected.
    expect(await within(region("Crawler")).findByText("I kö")).toBeTruthy();
    await expectNoAxeViolations(container);

    const retry = within(users).getByRole("button", { name: "Försök igen" });
    retry.focus();
    fireEvent.click(retry);
    expect(await within(users).findByText("42")).toBeTruthy();
    expect(within(users).queryByText("Innehållet kunde inte hämtas")).toBeNull();
    expect(attempts).toBe(2);
  });

  it("asks for an access session when the audit logs answer 401", async () => {
    answer({ ...ALL_OK, "/api/v1/audit/logs": failure(401) });
    renderOverview();

    const audit = region("Senaste granskningshändelser");
    expect(
      await within(audit).findByText(
        "Granskningsloggarna visas först efter en motiverad åtkomstsession."
      )
    ).toBeTruthy();
    expect(
      within(audit).getByRole("link", { name: "Öppna granskningsloggarna" }).getAttribute("href")
    ).toBe("/admin/audit-logs");
    expect(within(audit).queryByRole("button", { name: "Försök igen" })).toBeNull();
    // Any other failure gets the generic error with retry.
    cleanup();
    answer({ ...ALL_OK, "/api/v1/audit/logs": failure(500) });
    renderOverview();
    expect(
      await within(region("Senaste granskningshändelser")).findByRole("button", {
        name: "Försök igen"
      })
    ).toBeTruthy();
  });

  it("says so when a tenant has nothing yet, instead of showing zeros", async () => {
    answer({
      ...ALL_OK,
      "/api/v1/token-usage/": ok({
        ...USAGE,
        models: [],
        total_input_token_usage: 0,
        total_output_token_usage: 0,
        total_token_usage: 0
      }),
      "/api/v1/admin/crawler/": ok({
        ...CRAWLER,
        summary: { ongoing: 0, queued: 0, issues: 0 },
        scheduler: { ...CRAWLER.scheduler, status: "unknown", ran_at: null }
      }),
      "/api/v1/audit/logs": ok({ ...AUDIT, logs: [], total_count: 0 })
    });
    const { container } = renderOverview();

    expect(
      await within(region("Tokenanvändning senaste 30 dagarna")).findByText(
        "Ingen användning de senaste 30 dagarna."
      )
    ).toBeTruthy();
    const crawler = region("Crawler");
    expect(await within(crawler).findByText("Inga indexeringar pågår eller väntar.")).toBeTruthy();
    expect(within(crawler).getByText("Status okänd")).toBeTruthy();
    expect(
      await within(region("Senaste granskningshändelser")).findByText(
        "Inga händelser har loggats ännu."
      )
    ).toBeTruthy();
    // The links to each page stay, so the admin can still get there.
    expect(screen.getAllByRole("link")).toHaveLength(4);
    await waitFor(() => expect(document.querySelector('[aria-busy="true"]')).toBeNull());
    await expectNoAxeViolations(container);
  });
});
