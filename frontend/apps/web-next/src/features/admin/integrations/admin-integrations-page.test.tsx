// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import type { Schema } from "@/lib/api/models";
import { SHAREPOINT_APP_KEY, TENANT_INTEGRATIONS_KEY } from "./integrations";
import { AdminIntegrationsPage } from "./admin-integrations-page";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });
const app: Schema<"TenantSharePointAppPublic"> = {
  id: "app",
  tenant_id: "tenant",
  client_id: "client",
  client_secret_masked: "****1234",
  tenant_domain: "example.onmicrosoft.com",
  is_active: true,
  auth_method: "tenant_app",
  certificate_path: null,
  created_by: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z"
};
function show(read: () => Promise<unknown>) {
  api.GET.mockImplementation((path: string) =>
    path === "/api/v1/admin/sharepoint/app" ? read() : ok([])
  );
  const queryClient = testQueryClient();
  queryClient.setQueryData(TENANT_INTEGRATIONS_KEY, []);
  renderInApp(<AdminIntegrationsPage />, { queryClient });
  return { queryClient, section: screen.getByRole("region", { name: "SharePoint-anslutning" }) };
}
it("keeps configuration controls out of initial loading, then shows a genuine unconfigured state", async () => {
  let finish!: (value: unknown) => void;
  const { section } = show(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  expect(within(section).getByText("Laddar konfiguration...")).toBeTruthy();
  expect(within(section).queryByRole("button", { name: "Konfigurera" })).toBeNull();
  await act(async () => {
    finish({ data: null, response: new Response("{}") });
  });
  expect(await within(section).findByRole("button", { name: "Konfigurera" })).toBeTruthy();
});
it("retries an initial config error without presenting it as an unconfigured app", async () => {
  let failed = true;
  const { section } = show(() =>
    failed
      ? Promise.resolve({
          error: { message: "Unavailable" },
          response: new Response("{}", { status: 503 })
        })
      : ok(null)
  );
  const retry = await within(section).findByRole("button", { name: /Försök igen/ });
  expect(within(section).queryByRole("button", { name: "Konfigurera" })).toBeNull();
  failed = false;
  fireEvent.click(retry);
  expect(await within(section).findByRole("button", { name: "Konfigurera" })).toBeTruthy();
});
it.each([
  ["ok", "Inloggning verifierad"],
  ["error", "Inloggningsproblem"],
  ["unknown", "Inloggning inte verifierad än"]
] as const)(
  "keeps configured %s health on screen when a refresh fails",
  async (auth_status, label) => {
    let failed = false;
    const { queryClient, section } = show(() =>
      failed
        ? Promise.resolve({
            error: { message: "Unavailable" },
            response: new Response("{}", { status: 503 })
          })
        : ok({ ...app, auth_status })
    );
    expect(await within(section).findByText(label)).toBeTruthy();
    failed = true;
    await act(async () => {
      await queryClient.invalidateQueries({ queryKey: SHAREPOINT_APP_KEY });
    });
    await waitFor(() =>
      expect(within(section).getByRole("button", { name: /Försök igen/ })).toBeTruthy()
    );
    expect(within(section).getByText(label)).toBeTruthy();
    expect(
      within(section).getAllByRole("button", { name: "Uppdatera konfiguration" }).length
    ).toBeGreaterThan(0);
    expect(within(section).queryByRole("button", { name: "Konfigurera" })).toBeNull();
  }
);
it("offers SharePoint only to enable, as production does", () => {
  api.GET.mockImplementation(() => ok(null));
  const queryClient = testQueryClient();
  const provider = (integration_type: string, name: string) => ({
    id: null,
    integration_id: integration_type,
    name,
    description: "",
    integration_type,
    is_linked_to_tenant: false
  });
  queryClient.setQueryData(TENANT_INTEGRATIONS_KEY, [
    provider("sharepoint", "SharePoint / OneDrive"),
    provider("confluence", "Confluence")
  ]);
  renderInApp(<AdminIntegrationsPage />, { queryClient });
  expect(screen.getByText("SharePoint / OneDrive")).toBeTruthy();
  expect(screen.queryByText("Confluence")).toBeNull();
  expect(screen.getAllByRole("button", { name: "Aktivera" })).toHaveLength(1);
});
