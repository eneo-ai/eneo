// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useQuery } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { QueryAppContextProvider } from "@/components/providers/app-context-from-queries";
import { AdminSections } from "@/components/shell/admin-nav";
import { browserApi } from "@/lib/api/browser";
import { makeQueryClient } from "@/lib/api/query";
import { loadSession, sessionKeys } from "@/lib/api/session";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import {
  flushAnnouncements,
  recordAnnouncements,
  renderHookInApp,
  renderInApp,
  testAppContext,
  testQueryClient
} from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn(), PATCH: vi.fn() }));
const toastApiError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/api/toast", () => ({ toastApiError }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

import { FeatureToggles } from "./feature-toggles";

const WORKERS_PATH = "/api/v1/settings/task-workers";

type Workers = {
  probe_ok: boolean;
  execution_worker_ready: boolean;
  maintenance_worker_ready: boolean;
};

const bothRunning: Workers = {
  probe_ok: true,
  execution_worker_ready: true,
  maintenance_worker_ready: true
};

function answerWorkers(workers: Workers) {
  api.GET.mockResolvedValue({ data: workers, response: new Response("{}") });
}

beforeEach(() => answerWorkers(bothRunning));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderToggles(queryClient = testQueryClient(), flowsEnabled = false) {
  renderInApp(<FeatureToggles />, {
    queryClient,
    appContext: testAppContext({
      settings: {
        using_templates: true,
        audit_logging_enabled: false,
        provisioning: false,
        whats_new_enabled: true,
        flows_enabled: flowsEnabled
      }
    })
  });
  return vi.spyOn(queryClient, "invalidateQueries");
}

const saved = () => Promise.resolve({ data: { enabled: true }, response: new Response("{}") });

it("renders labelled, described switches in a titled card", async () => {
  renderToggles();
  expect(screen.getByRole("region", { name: "Funktioner" })).toBeTruthy();
  const templates = screen.getByRole("switch", { name: "Mallar" });
  // The icon tile is the row's first part, hidden on a phone.
  expect(templates.closest("li")?.firstElementChild?.firstElementChild?.className).toContain(
    "max-md:hidden"
  );
  expect((templates as HTMLInputElement).checked).toBe(true);
  expect(templates.getAttribute("aria-describedby")).toBeTruthy();
  const described = document.getElementById(templates.getAttribute("aria-describedby")!);
  expect(described?.textContent).toBe(messages.enable_templates_description);
  expect(screen.getAllByRole("switch")).toHaveLength(5);
  await expectNoAxeViolations(document.body);
});

it("refreshes both provisioning resources without refetching unrelated session data", async () => {
  const queryClient = testQueryClient();
  let settings = { provisioning: false };
  let tenant = { provisioning: false };
  const getSettings = vi.fn(async () => settings);
  const getTenant = vi.fn(async () => tenant);
  const getUser = vi.fn(async () => ({ id: "user-1" }));
  const { result } = renderHookInApp(
    () => ({
      settings: useQuery({
        queryKey: sessionKeys.settings,
        queryFn: getSettings,
        staleTime: Infinity
      }).data,
      tenant: useQuery({ queryKey: sessionKeys.tenant, queryFn: getTenant, staleTime: Infinity })
        .data,
      user: useQuery({ queryKey: sessionKeys.me, queryFn: getUser, staleTime: Infinity }).data
    }),
    { queryClient }
  );
  await waitFor(() => expect(result.current).toEqual({ settings, tenant, user: { id: "user-1" } }));
  api.PATCH.mockImplementation(async (_path, { body }) => {
    settings = { provisioning: body.enabled };
    tenant = { provisioning: body.enabled };
    return { data: settings, response: new Response("{}") };
  });
  renderToggles(queryClient);
  fireEvent.click(screen.getByRole("switch", { name: "Automatisk kontoskapning (SSO)" }));
  await waitFor(() => expect(result.current.settings?.provisioning).toBe(true));
  await waitFor(() => expect(result.current.tenant?.provisioning).toBe(true));
  expect(getSettings).toHaveBeenCalledTimes(2);
  expect(getTenant).toHaveBeenCalledTimes(2);
  expect(getUser).toHaveBeenCalledTimes(1);
});

it("saves a toggle and refreshes the shared settings", async () => {
  api.PATCH.mockResolvedValue({ data: { enabled: true }, response: new Response("{}") });
  const invalidate = renderToggles();
  const audit = screen.getByRole("switch", { name: "Granskningsloggning" });

  fireEvent.click(audit);

  await waitFor(() => expect((audit as HTMLInputElement).checked).toBe(true));
  expect(api.PATCH).toHaveBeenCalledWith("/api/v1/settings/audit-logging", {
    body: { enabled: true }
  });
  await waitFor(() =>
    expect(invalidate).toHaveBeenCalledExactlyOnceWith({ queryKey: sessionKeys.settings })
  );
  // The switch keeps focus while saving: it is never disabled.
  expect((audit as HTMLInputElement).disabled).toBe(false);
});

it("reverts and reports the error when saving fails", async () => {
  api.PATCH.mockResolvedValue({
    error: { message: "nope" },
    response: new Response("{}", { status: 500 })
  });
  const invalidate = renderToggles();
  const provisioning = screen.getByRole("switch", { name: "Automatisk kontoskapning (SSO)" });

  fireEvent.click(provisioning);

  await waitFor(() => expect(toastApiError).toHaveBeenCalled());
  expect((provisioning as HTMLInputElement).checked).toBe(false);
  expect(invalidate).not.toHaveBeenCalled();
});

it("saves a press made during a save once that save is done", async () => {
  const saves: Array<() => void> = [];
  api.PATCH.mockImplementation(() => new Promise((resolve) => saves.push(() => resolve(saved()))));
  const invalidate = renderToggles();
  const audit = screen.getByRole("switch", { name: "Granskningsloggning" });

  fireEvent.click(audit);
  await waitFor(() => expect((audit as HTMLInputElement).checked).toBe(true));
  // Pressed again while the first save runs: shown at once, not dropped.
  fireEvent.click(audit);
  await waitFor(() => expect((audit as HTMLInputElement).checked).toBe(false));
  expect(api.PATCH).toHaveBeenCalledTimes(1);

  await act(async () => saves[0]!());
  await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(2));
  expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/settings/audit-logging", {
    body: { enabled: false }
  });
  await act(async () => saves[1]!());
  await waitFor(() => expect(invalidate).toHaveBeenCalledTimes(2));
  expect((audit as HTMLInputElement).checked).toBe(false);
});

function flowsRow() {
  return screen.getByRole("switch", { name: "Flöden" }).closest("li") as HTMLElement;
}

it("shows Flows as alpha, with the workers it needs and how roles get access", async () => {
  renderToggles();
  const row = flowsRow();
  const flows = within(row).getByRole("switch", { name: "Flöden" }) as HTMLInputElement;

  expect(flows.checked).toBe(false);
  expect(within(row).getByText("Alfa")).toBeTruthy();
  expect(row.textContent).toContain(messages.flows_switch_description);
  expect(
    within(row).getByRole("link", { name: "Administration > Roller" }).getAttribute("href")
  ).toBe("/admin/roles");
  expect(await within(row).findByText("Arbetarna: Kör")).toBeTruthy();
  expect(row.textContent).toContain(messages.flows_switch_workers_basis);
  expect(api.GET).toHaveBeenCalledWith(WORKERS_PATH);
  await expectNoAxeViolations(document.body);
});

it.each([
  [{ ...bothRunning, execution_worker_ready: false }, "Arbetarna: Kör inte: task-execution-worker"],
  [
    { ...bothRunning, maintenance_worker_ready: false },
    "Arbetarna: Kör inte: task-maintenance-worker"
  ],
  [
    { ...bothRunning, execution_worker_ready: false, maintenance_worker_ready: false },
    "Arbetarna: Kör inte: båda arbetarna"
  ],
  [
    { probe_ok: false, execution_worker_ready: false, maintenance_worker_ready: false },
    "Arbetarna: Kunde inte kontrolleras"
  ]
])("names the workers' state %#", async (workers, label) => {
  answerWorkers(workers);
  renderToggles();
  expect(await within(flowsRow()).findByText(label)).toBeTruthy();
});

it.each([
  [
    "a failed request",
    { error: { message: "down" }, response: new Response("{}", { status: 503 }) }
  ],
  [
    "a probe that could not read the workers",
    {
      data: { probe_ok: false, execution_worker_ready: false, maintenance_worker_ready: false },
      response: new Response("{}")
    }
  ]
])("shows %s after a green check as not checked, never as still running", async (_, reply) => {
  // The app's own client, with its retries: the state must not wait them out.
  renderToggles(makeQueryClient());
  const row = flowsRow();
  expect(await within(row).findByText("Arbetarna: Kör")).toBeTruthy();
  api.GET.mockResolvedValue(reply);

  fireEvent.click(within(row).getByRole("button", { name: "Uppdatera arbetarnas läge" }));

  expect(await within(row).findByText("Arbetarna: Kunde inte kontrolleras")).toBeTruthy();
  expect(within(row).queryByText("Arbetarna: Kör")).toBeNull();
  expect(api.GET).toHaveBeenCalledTimes(2);
  expect(row.textContent).toContain("Senaste försök");
  expect(row.textContent).not.toContain("Kontrollerad");
});

it("dates a probe that could not read the workers as an attempt, not a check", async () => {
  answerWorkers({
    probe_ok: false,
    execution_worker_ready: false,
    maintenance_worker_ready: false
  });
  renderToggles();
  const row = flowsRow();
  expect(await within(row).findByText("Arbetarna: Kunde inte kontrolleras")).toBeTruthy();
  expect(row.textContent).toContain("Senaste försök");
  expect(row.textContent).not.toContain("Kontrollerad");
});

const FLOWS_GUIDE = "https://docs.eneo.ai/dev/sv/guides/flows/integrating-flows#switch-flows-on";

it("links the Flows setup guide, and points to it for the workers when they do not run", async () => {
  renderToggles();
  const row = flowsRow();
  expect(await within(row).findByText("Arbetarna: Kör")).toBeTruthy();
  const guide = within(row).getByRole("link", { name: /Så sätter du upp Flöden/ });
  expect(guide.getAttribute("href")).toBe(FLOWS_GUIDE);
  expect(within(row).queryByRole("link", { name: /Så får du arbetarna att köra/ })).toBeNull();

  cleanup();
  answerWorkers({ ...bothRunning, execution_worker_ready: false });
  renderToggles();
  const stopped = flowsRow();
  expect(
    await within(stopped).findByText("Arbetarna: Kör inte: task-execution-worker")
  ).toBeTruthy();
  const workersGuide = within(stopped).getByRole("link", { name: /Så får du arbetarna att köra/ });
  expect(workersGuide.getAttribute("href")).toBe(FLOWS_GUIDE);
  await expectNoAxeViolations(document.body);
});

it("checks the workers again as soon as Flows are switched on", async () => {
  api.PATCH.mockResolvedValue({ data: {}, response: new Response("{}") });
  renderToggles();
  const row = flowsRow();
  expect(await within(row).findByText("Arbetarna: Kör")).toBeTruthy();
  answerWorkers({ ...bothRunning, execution_worker_ready: false });

  fireEvent.click(within(row).getByRole("switch", { name: "Flöden" }));

  expect(await within(row).findByText("Arbetarna: Kör inte: task-execution-worker")).toBeTruthy();
  expect(api.GET.mock.calls.filter(([path]) => path === WORKERS_PATH)).toHaveLength(2);
});

it("announces the workers' state that switching Flows on checked", async () => {
  api.PATCH.mockResolvedValue({ data: {}, response: new Response("{}") });
  const said = recordAnnouncements();
  renderToggles();
  const row = flowsRow();
  expect(await within(row).findByText("Arbetarna: Kör")).toBeTruthy();
  await flushAnnouncements();
  answerWorkers({ ...bothRunning, execution_worker_ready: false });

  fireEvent.click(within(row).getByRole("switch", { name: "Flöden" }));

  await waitFor(() => expect(said).toContain("Arbetarna: Kör inte: task-execution-worker"));
  const afterSwitch = said.length;

  // Refresh is its own action and says its own result once.
  fireEvent.click(within(row).getByRole("button", { name: "Uppdatera arbetarnas läge" }));
  await waitFor(() => expect(said.length).toBeGreaterThan(afterSwitch));
  await flushAnnouncements();
  expect(said.slice(afterSwitch)).toEqual(["Arbetarna: Kör inte: task-execution-worker"]);
});

it("announces the workers' state without waiting for the settings to reload", async () => {
  const queryClient = testQueryClient();
  let releaseSettings = () => {};
  const getSettings = vi
    .fn()
    .mockResolvedValueOnce({ flows_enabled: false })
    .mockReturnValueOnce(
      new Promise((resolve) => {
        releaseSettings = () => resolve({ flows_enabled: true });
      })
    );
  renderHookInApp(
    () => useQuery({ queryKey: sessionKeys.settings, queryFn: getSettings, staleTime: Infinity }),
    { queryClient }
  );
  await waitFor(() => expect(getSettings).toHaveBeenCalledTimes(1));
  api.PATCH.mockResolvedValue({ data: {}, response: new Response("{}") });
  const said = recordAnnouncements();
  renderToggles(queryClient);
  const row = flowsRow();
  expect(await within(row).findByText("Arbetarna: Kör")).toBeTruthy();
  await flushAnnouncements();
  answerWorkers({ ...bothRunning, execution_worker_ready: false });

  fireEvent.click(within(row).getByRole("switch", { name: "Flöden" }));

  await waitFor(() => expect(said).toContain("Arbetarna: Kör inte: task-execution-worker"));
  // The settings are still reloading.
  expect(getSettings).toHaveBeenCalledTimes(2);
  releaseSettings();
});

it("announces a check after switching Flows on that could not be made", async () => {
  api.PATCH.mockResolvedValue({ data: {}, response: new Response("{}") });
  const said = recordAnnouncements();
  renderToggles();
  const row = flowsRow();
  expect(await within(row).findByText("Arbetarna: Kör")).toBeTruthy();
  await flushAnnouncements();
  api.GET.mockResolvedValue({
    error: { message: "down" },
    response: new Response("{}", { status: 503 })
  });

  fireEvent.click(within(row).getByRole("switch", { name: "Flöden" }));

  await waitFor(() => expect(said).toContain("Arbetarna: Kunde inte kontrolleras"));
});

it("asks before switching Flows off, and Cancel sends nothing", async () => {
  api.PATCH.mockResolvedValue({ data: {}, response: new Response("{}") });
  renderToggles(testQueryClient(), true);
  const flows = screen.getByRole("switch", { name: "Flöden" }) as HTMLInputElement;
  expect(flows.checked).toBe(true);

  fireEvent.click(flows);
  const dialog = await screen.findByRole("alertdialog", { name: "Stäng av Flöden?" });
  expect(dialog.textContent).toContain(messages.flows_switch_off_description);
  fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));

  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(api.PATCH).not.toHaveBeenCalled();
  expect(flows.checked).toBe(true);

  fireEvent.click(flows);
  const again = await screen.findByRole("alertdialog", { name: "Stäng av Flöden?" });
  fireEvent.click(within(again).getByRole("button", { name: "Stäng av Flöden" }));

  await waitFor(() =>
    expect(api.PATCH).toHaveBeenCalledExactlyOnceWith("/api/v1/settings/flows", {
      body: { enabled: false }
    })
  );
  await waitFor(() => expect(flows.checked).toBe(false));
});

it("leaves Flows off when switching them on fails", async () => {
  api.PATCH.mockResolvedValue({
    error: { message: "nope" },
    response: new Response("{}", { status: 500 })
  });
  renderToggles();
  const flows = screen.getByRole("switch", { name: "Flöden" }) as HTMLInputElement;

  fireEvent.click(flows);

  await waitFor(() => expect(toastApiError).toHaveBeenCalled());
  expect(flows.checked).toBe(false);
  expect(screen.queryByRole("alertdialog")).toBeNull();
});

it("leaves Flows on when switching them off fails", async () => {
  api.PATCH.mockResolvedValue({
    error: { message: "nope" },
    response: new Response("{}", { status: 500 })
  });
  renderToggles(testQueryClient(), true);
  const flows = screen.getByRole("switch", { name: "Flöden" }) as HTMLInputElement;

  fireEvent.click(flows);
  const dialog = await screen.findByRole("alertdialog", { name: "Stäng av Flöden?" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Stäng av Flöden" }));

  await waitFor(() => expect(toastApiError).toHaveBeenCalled());
  expect(flows.checked).toBe(true);
  expect(screen.queryByRole("alertdialog")).toBeNull();
});

it("switches Flows on and off without a reload, and the admin menu follows", async () => {
  const base = testAppContext({ permissions: ["admin"] });
  let settings = { ...base.settings, whats_new_enabled: false, flows_enabled: false };
  const replies = new Map<string, unknown>([
    ["/api/v1/users/me/", base.user],
    ["/api/v1/users/tenant/", base.tenant],
    ["/api/v1/auth/federation-status", base.federationStatus],
    ["/api/v1/limits/", base.limits],
    ["/api/v1/whats-new/state/", null],
    [WORKERS_PATH, bothRunning]
  ]);
  api.GET.mockImplementation(async (path: string) => ({
    data: path === "/api/v1/settings/" ? settings : replies.get(path),
    response: new Response("{}")
  }));
  api.PATCH.mockImplementation(async (_path: string, { body }: { body: { enabled: boolean } }) => {
    settings = { ...settings, flows_enabled: body.enabled };
    return { data: settings, response: new Response("{}") };
  });
  const queryClient = testQueryClient();
  await loadSession(queryClient, browserApi);
  renderInApp(
    <QueryAppContextProvider env={{ links: base.links, frontendVersion: "1", backendVersion: "1" }}>
      <AdminSections />
      <FeatureToggles />
    </QueryAppContextProvider>,
    { queryClient }
  );
  expect(screen.queryByRole("link", { name: messages.flow_admin_nav_label })).toBeNull();

  fireEvent.click(screen.getByRole("switch", { name: "Flöden" }));

  expect(await screen.findByRole("link", { name: messages.flow_admin_nav_label })).toBeTruthy();
  expect(api.PATCH).toHaveBeenCalledWith("/api/v1/settings/flows", { body: { enabled: true } });
  expect((screen.getByRole("switch", { name: "Flöden" }) as HTMLInputElement).checked).toBe(true);

  fireEvent.click(screen.getByRole("switch", { name: "Flöden" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Stäng av Flöden?" });
  fireEvent.click(within(dialog).getByRole("button", { name: "Stäng av Flöden" }));

  await waitFor(() =>
    expect(screen.queryByRole("link", { name: messages.flow_admin_nav_label })).toBeNull()
  );
  expect(api.PATCH).toHaveBeenLastCalledWith("/api/v1/settings/flows", {
    body: { enabled: false }
  });
  expect((screen.getByRole("switch", { name: "Flöden" }) as HTMLInputElement).checked).toBe(false);
});
