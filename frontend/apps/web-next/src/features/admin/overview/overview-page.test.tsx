// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { setViewport } from "@/test/setup-dom";

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

const MODELS = {
  completion_models: [
    {
      id: "m1",
      name: "mistral-large",
      nickname: "Mistral Large",
      is_deprecated: false,
      is_org_enabled: true,
      is_org_default: true,
      provider_id: "p1",
      security_classification: null,
      supported_model_kwargs: {}
    }
  ],
  embedding_models: [],
  transcription_models: [],
  image_models: []
};

const CAPABILITIES = {
  providers: {},
  default_fields: [{ name: "api_key", required: true, secret: true, in: "credentials" }]
};

const provider = (overrides: Record<string, unknown> = {}) => ({
  id: "p1",
  tenant_id: "t",
  name: "Mistral",
  provider_type: "mistral",
  config: {},
  is_active: true,
  masked_api_key: "...4f2a",
  key_expires_on: null,
  connection_check: { status: "ok", checked_at: "2026-10-22T13:40:00Z", error: null },
  connection_check_supported: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  ...overrides
});

/** A date `days` from the viewer's today, as an ISO date. */
function inDays(days: number) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

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

const PROVIDERS = "/api/v1/admin/model-providers/";

const ALL_OK: Responses = {
  "/api/v1/admin/users/": ok(USERS),
  "/api/v1/token-usage/": ok(USAGE),
  "/api/v1/admin/crawler/": ok(CRAWLER),
  "/api/v1/audit/logs": ok(AUDIT),
  "/api/v1/ai-models/": ok(MODELS),
  [PROVIDERS]: ok([provider()]),
  "/api/v1/admin/model-providers/capabilities/": ok(CAPABILITIES)
};

/** Nothing for an admin to act on: the crawler has no issues either. */
const HEALTHY: Responses = {
  ...ALL_OK,
  "/api/v1/admin/crawler/": ok({ ...CRAWLER, summary: { ongoing: 1, queued: 2, issues: 0 } })
};

function renderOverview({ auditLogging = true, queryClient = testQueryClient() } = {}) {
  return renderInApp(<AdminOverviewPage />, {
    queryClient,
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

describe("Behöver åtgärd (decision 30)", () => {
  const attention = () => screen.queryByRole("region", { name: "Behöver åtgärd" });
  const rows = (region: HTMLElement) =>
    within(region)
      .getAllByRole("link")
      .map((link) => [link.textContent, link.getAttribute("href")]);

  it("leads the page when something needs an admin, errors first, each row to its fix", async () => {
    answer({
      ...ALL_OK,
      [PROVIDERS]: ok([
        provider({
          connection_check: {
            status: "failed",
            checked_at: "2026-10-22T13:40:00Z",
            error: "authentication_failed"
          }
        })
      ])
    });
    const { container } = renderOverview();

    const first = await screen.findByRole("region", { name: "Behöver åtgärd" });
    expect(screen.getAllByRole("region")[0]).toBe(first);
    expect(rows(first)).toEqual([
      [
        "Fel: Mistral, Anslutningen misslyckades: API-nyckeln godkändes inte",
        "/admin/models#provider-p1"
      ],
      ["Varning: Crawler, 4 fel och varningar", "/admin/crawler"]
    ]);
    await expectNoAxeViolations(container);
  });

  it.each([
    ["a missing key", { masked_api_key: null }, /^Varning: Mistral, /],
    [
      "a key that expires within 30 days",
      { key_expires_on: inDays(10) },
      /^Varning: Mistral, Nyckeln går ut /
    ],
    [
      "a key that has expired",
      { key_expires_on: inDays(-2) },
      /^Fel: Mistral, Nyckeln har gått ut /
    ]
  ])("raises one row for %s", async (_name, overrides, text) => {
    answer({ ...HEALTHY, [PROVIDERS]: ok([provider(overrides)]) });
    renderOverview();
    const [row, ...rest] = await within(
      await screen.findByRole("region", { name: "Behöver åtgärd" })
    ).findAllByRole("link");
    expect(rest).toEqual([]);
    expect(row!.textContent).toMatch(text);
    expect(row!.getAttribute("href")).toBe("/admin/models#provider-p1");
  });

  it("raises a row for deprecated models still in use", async () => {
    answer({
      ...HEALTHY,
      "/api/v1/ai-models/": ok({
        ...MODELS,
        completion_models: [{ ...MODELS.completion_models[0], is_deprecated: true }]
      })
    });
    renderOverview();
    const region = await screen.findByRole("region", { name: "Behöver åtgärd" });
    const [row] = await within(region).findAllByRole("link");
    expect(row!.textContent).toMatch(/^Varning: /);
    expect(row!.getAttribute("href")).toBe("/admin/models");
  });

  it.each([
    ["degraded", "Varning"],
    ["stale", "Fel"]
  ])("raises a row for a crawler scheduler that is %s", async (status, severity) => {
    answer({
      ...HEALTHY,
      "/api/v1/admin/crawler/": ok({
        ...CRAWLER,
        summary: { ongoing: 0, queued: 0, issues: 0 },
        scheduler: { ...CRAWLER.scheduler, status }
      })
    });
    renderOverview();
    const region = await screen.findByRole("region", { name: "Behöver åtgärd" });
    const [row] = await within(region).findAllByRole("link");
    // As the crawler's card says it: one that has not run is an error.
    expect(row!.textContent).toMatch(new RegExp(`^${severity}: Crawlerns schemaläggare, `));
    expect(row!.getAttribute("href")).toBe("/admin/crawler");
  });

  it("is not there when nothing needs an admin, or a signal cannot be read", async () => {
    answer(HEALTHY);
    renderOverview();
    expect(await within(region("Aktiva användare")).findByText("42")).toBeTruthy();
    await waitFor(() => expect(document.querySelector('[aria-busy="true"]')).toBeNull());
    expect(attention()).toBeNull();

    cleanup();
    answer({ ...HEALTHY, [PROVIDERS]: () => Promise.reject(new Error("offline")) });
    renderOverview();
    expect(await within(region("Aktiva användare")).findByText("42")).toBeTruthy();
    expect(attention()).toBeNull();
  });
});

describe("AdminOverviewPage on a phone (decision 30)", () => {
  it("lists the areas as rows with how each stands, not as cards", async () => {
    setViewport("phone");
    answer(HEALTHY);
    const { container } = renderOverview();

    const areas = await screen.findByRole("region", { name: "Läget just nu" });
    const links = within(areas).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/admin/users",
      "/admin/models",
      "/admin/usage",
      "/admin/crawler",
      "/admin/audit-logs"
    ]);
    expect(await within(areas).findByText("42 aktiva · 3 inaktiva konton")).toBeTruthy();
    expect(await within(areas).findByText("1 av 1 aktiva")).toBeTruthy();
    expect(await within(areas).findByText(/^2\s?000 tokens, 30 dagar · 2 modeller$/)).toBeTruthy();
    expect(await within(areas).findByText("1 pågående · 2 i kö")).toBeTruthy();
    // The latest event, and when it was.
    expect(
      await within(areas).findByRole("link", {
        name: /^Granskningsloggar ?, Senast: Anna Lind bytte lösenord, \S/
      })
    ).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Aktiva användare" })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("counts the models the Modeller page lists, and repeats what needs an admin there", async () => {
    setViewport("phone");
    answer({
      ...HEALTHY,
      // A built-in global model has no provider: the Modeller page leaves it out.
      "/api/v1/ai-models/": ok({
        ...MODELS,
        completion_models: [
          ...MODELS.completion_models,
          { ...MODELS.completion_models[0], id: "g1", provider_id: null }
        ]
      }),
      [PROVIDERS]: ok([provider({ masked_api_key: null })])
    });
    renderOverview();
    const areas = await screen.findByRole("region", { name: "Läget just nu" });
    expect(
      await within(areas).findByRole("link", {
        name: /^Modeller ?, Behöver åtgärd ?· 1 av 1 aktiva$/
      })
    ).toBeTruthy();
  });

  it("keeps the audit logs locked while their query asks again", async () => {
    setViewport("phone");
    const queryClient = testQueryClient();
    answer({ ...HEALTHY, "/api/v1/audit/logs": failure(401) });
    renderOverview({ queryClient });
    const areas = await screen.findByRole("region", { name: "Läget just nu" });
    const locked = "Granskningsloggarna visas först efter en motiverad åtkomstsession.";
    expect(await within(areas).findByText(locked)).toBeTruthy();

    // A refetch clears the query's error while it runs.
    answer({ ...HEALTHY, "/api/v1/audit/logs": () => new Promise(() => {}) });
    act(() => {
      void queryClient.refetchQueries({ type: "active" });
    });
    await waitFor(() => expect(queryClient.isFetching()).toBeGreaterThan(0));
    expect(within(areas).getByText(locked)).toBeTruthy();
    expect(within(areas).queryByText("Innehållet kunde inte hämtas")).toBeNull();
  });

  it("leaves Granskningsloggar out while audit logging is off", async () => {
    setViewport("phone");
    answer(HEALTHY);
    renderOverview({ auditLogging: false });
    const areas = await screen.findByRole("region", { name: "Läget just nu" });
    await within(areas).findByText("42 aktiva · 3 inaktiva konton");
    expect(within(areas).queryByRole("link", { name: /^Granskningsloggar/ })).toBeNull();
  });
});
