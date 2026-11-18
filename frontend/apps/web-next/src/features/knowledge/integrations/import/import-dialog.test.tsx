// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testAppContext } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
const space = vi.hoisted(() => ({ current: null as unknown }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => ({ trackJob: vi.fn() }) }));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => space.current as Space) };
});

import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { ImportKnowledgeDialog } from "./import-dialog";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

const integration = (
  id: string,
  name: string,
  integration_type: "sharepoint" | "confluence",
  connected: boolean
) => ({
  id: `user-${id}`,
  name,
  description: "",
  integration_type,
  tenant_integration_id: id,
  connected,
  auth_type: "user_oauth"
});

it.each([
  { personal: true, admin: false, href: "/account/integrations?tab=providers" },
  { personal: false, admin: true, href: "/admin/integrations?tab=providers" },
  { personal: false, admin: false, href: null }
])("offers the authorized setup from an empty dialog: %j", async ({ personal, admin, href }) => {
  space.current = makeSpace({ overrides: { personal } });
  api.GET.mockImplementation(() => ok({ items: [] }));
  renderInApp(<ImportKnowledgeDialog open onOpenChange={() => {}} />, {
    appContext: testAppContext({ permissions: admin ? ["admin"] : [] })
  });
  await screen.findByText("Inga integrationer tillgängliga.");
  if (href)
    expect(
      screen.getByRole("link", { name: "Konfigurera integrationer" }).getAttribute("href")
    ).toBe(href);
  else {
    expect(screen.queryByRole("link", { name: "Konfigurera integrationer" })).toBeNull();
    expect(screen.getByText(/administratör/i)).toBeTruthy();
  }
});

it("offers the integrations as a radio group; one not connected says why", async () => {
  space.current = makeSpace({ overrides: { personal: true } });
  api.GET.mockImplementation((path: string) =>
    path.endsWith("/available/")
      ? ok({
          items: [
            integration("sp", "Intranät", "sharepoint", true),
            integration("archive", "Arkiv", "sharepoint", false)
          ]
        })
      : ok({ items: [] })
  );
  renderInApp(<ImportKnowledgeDialog open onOpenChange={() => {}} />);
  const dialog = await screen.findByRole("dialog", { name: "Importera kunskap" });

  const choices = await within(dialog).findByRole("radiogroup", { name: "Integrationer" });
  const intranet = within(choices).getByRole("radio", { name: /Intranät/ });
  const archive = within(choices).getByRole("radio", { name: /Arkiv/ });
  // The first connected one is chosen; the other cannot be.
  expect((intranet as HTMLInputElement).checked).toBe(true);
  expect((archive as HTMLInputElement).disabled).toBe(true);
  expect(
    within(choices).getByText(
      "Aktivera Arkiv i dina kontoinställningar för att välja detta alternativ"
    )
  ).toBeTruthy();
  await expectNoAxeViolations(dialog);
});

it("offers SharePoint only, and continues with the integration chosen", async () => {
  space.current = makeSpace({ overrides: { personal: true } });
  api.GET.mockImplementation((path: string) =>
    path.endsWith("/available/")
      ? ok({
          items: [
            integration("sp", "Intranät", "sharepoint", true),
            integration("cf", "Confluence", "confluence", true),
            integration("archive", "Arkiv", "sharepoint", true)
          ]
        })
      : ok({ items: [] })
  );
  renderInApp(<ImportKnowledgeDialog open onOpenChange={() => {}} />);
  const dialog = await screen.findByRole("dialog", { name: "Importera kunskap" });
  const archive = await within(dialog).findByRole("radio", { name: /Arkiv/ });
  expect(within(dialog).getAllByRole("radio")).toHaveLength(2);
  expect(within(dialog).queryByRole("radio", { name: /Confluence/ })).toBeNull();

  fireEvent.click(archive);
  expect((archive as HTMLInputElement).checked).toBe(true);
  fireEvent.click(within(dialog).getByRole("button", { name: "Fortsätt" }));

  expect(
    await screen.findByRole("dialog", { name: "Importera kunskap från SharePoint / OneDrive" })
  ).toBeTruthy();
});
