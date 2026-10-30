// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import { AccountIntegrations } from "./account-integrations";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const api = vi.hoisted(() => ({ GET: vi.fn(), DELETE: vi.fn(), reportError: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/api/toast", () => ({ toastApiError: api.reportError }));

type UserIntegration = Schema<"UserIntegration">;
let items: UserIntegration[];
function integration(overrides: Partial<UserIntegration> = {}): UserIntegration {
  return {
    id: "user-integration",
    tenant_integration_id: "tenant-integration",
    name: "SharePoint",
    description: "Organisationens dokument",
    integration_type: "sharepoint",
    connected: true,
    auth_type: "user_oauth",
    ...overrides
  };
}

beforeEach(() => {
  items = [];
  api.GET.mockImplementation(() =>
    Promise.resolve({ data: { items, count: items.length }, response: new Response("{}") })
  );
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("keeps an API failure retryable before showing the empty list", async () => {
  api.GET.mockResolvedValueOnce({
    error: { message: "Unavailable" },
    response: new Response("{}", { status: 500 })
  });
  renderInApp(<AccountIntegrations />);
  fireEvent.click(await screen.findByRole("button", { name: "Försök igen" }));
  expect(
    await screen.findByText("Din organisation har för närvarande inga integrationer aktiverade.")
  ).toBeTruthy();
  expect(screen.queryByRole("link", { name: "administrationsmenyn för integrationer" })).toBeNull();
});

it("shows only SharePoint with vendor icons and personal or organisation identity", async () => {
  items = [
    integration(),
    integration({ id: "organisation", name: "Gemensamma dokument", auth_type: "tenant_app" }),
    integration({ id: "future", name: "Confluence", integration_type: "confluence" })
  ];
  const { container } = renderInApp(<AccountIntegrations />);
  expect(await screen.findByText("Personlig")).toBeTruthy();
  expect(screen.getByText("Organisation")).toBeTruthy();
  expect(screen.queryByText("Confluence")).toBeNull();
  expect(
    [...container.querySelectorAll("img")].map((img) => [img.getAttribute("src"), img.alt])
  ).toEqual([
    ["/integration-logos/sharepoint.png", ""],
    ["/integration-logos/sharepoint.png", ""]
  ]);
  await expectNoAxeViolations(container);
});

it("points admins to provider settings when the available types are not ready", async () => {
  items = [integration({ integration_type: "confluence", name: "Confluence" })];
  renderInApp(<AccountIntegrations />, { appContext: testAppContext({ permissions: ["admin"] }) });
  const link = await screen.findByRole("link", { name: "administrationsmenyn för integrationer" });
  expect(link.getAttribute("href")).toBe("/admin/integrations?tab=providers");
  expect(screen.getByText("Du kan aktivera integrationer i")).toBeTruthy();
});

it("requires confirmation, allows cancellation and keeps a failed disconnect retryable", async () => {
  items = [integration()];
  api.DELETE.mockResolvedValueOnce({
    error: { message: "Unavailable" },
    response: new Response("{}", { status: 503 })
  });
  api.DELETE.mockImplementation(async () => {
    items = [integration({ connected: false })];
    return { data: undefined, response: new Response(null, { status: 204 }) };
  });
  renderInApp(<AccountIntegrations />);
  fireEvent.click(await screen.findByRole("button", { name: "Koppla från" }));
  let dialog = screen.getByRole("alertdialog", { name: "Koppla från SharePoint" });
  expect(within(dialog).getByText("Vill du verkligen koppla från SharePoint?")).toBeTruthy();
  expect(api.DELETE).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);
  fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(api.DELETE).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Koppla från" }));
  dialog = screen.getByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Koppla från" }));
  await waitFor(() => expect(api.reportError).toHaveBeenCalledOnce());
  expect(screen.getByRole("alertdialog")).toBeTruthy();
  await waitFor(() =>
    expect(
      within(dialog).getByRole("button", { name: "Koppla från" }).getAttribute("aria-busy")
    ).toBeNull()
  );
  within(dialog).getByRole("button", { name: "Koppla från" }).focus();
  fireEvent.click(within(dialog).getByRole("button", { name: "Koppla från" }));
  await screen.findByRole("button", { name: "Anslut" });
  expect(screen.queryByRole("alertdialog")).toBeNull();
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("region", { name: "Integrationer" }))
  );
  expect(api.DELETE).toHaveBeenCalledTimes(2);
  expect(api.DELETE).toHaveBeenLastCalledWith("/api/v1/integrations/users/{user_integration_id}/", {
    params: { path: { user_integration_id: "user-integration" } }
  });
});

it("does not offer disconnect without a user connection id", async () => {
  items = [integration({ id: undefined })];
  renderInApp(<AccountIntegrations />);
  expect(await screen.findByRole("button", { name: "Anslut" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Koppla från" })).toBeNull();
});

it("explains unavailable tenant configuration without offering an action", async () => {
  items = [integration({ tenant_app_configured: false })];
  renderInApp(<AccountIntegrations />);
  expect(
    (await screen.findByRole("button", { name: "Inte tillgänglig" })).hasAttribute("disabled")
  ).toBe(true);
  expect(
    screen.getByText("Kontakta din administratör för att aktivera denna integration")
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Koppla från" })).toBeNull();
});
