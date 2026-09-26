// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
const space = vi.hoisted(() => ({ current: null as unknown }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
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

it("offers the integrations as a radio group; one not connected says why", async () => {
  space.current = makeSpace({ overrides: { personal: true } });
  api.GET.mockImplementation((path: string) =>
    path.endsWith("/available/")
      ? ok({
          items: [
            integration("sp", "SharePoint", "sharepoint", true),
            integration("cf", "Confluence", "confluence", false)
          ]
        })
      : ok({ items: [] })
  );
  renderInApp(<ImportKnowledgeDialog open onOpenChange={() => {}} />);
  const dialog = await screen.findByRole("dialog", { name: "Importera kunskap" });

  const choices = await within(dialog).findByRole("radiogroup", { name: "Integrationer" });
  const sharepoint = within(choices).getByRole("radio", { name: /SharePoint/ });
  const confluence = within(choices).getByRole("radio", { name: /Confluence/ });
  // The first connected one is chosen; the other cannot be.
  expect((sharepoint as HTMLInputElement).checked).toBe(true);
  expect((confluence as HTMLInputElement).disabled).toBe(true);
  expect(
    within(choices).getByText(
      "Aktivera Confluence i dina kontoinställningar för att välja detta alternativ"
    )
  ).toBeTruthy();
  await expectNoAxeViolations(dialog);
});

it("continues with the integration chosen", async () => {
  space.current = makeSpace({ overrides: { personal: true } });
  api.GET.mockImplementation((path: string) =>
    path.endsWith("/available/")
      ? ok({
          items: [
            integration("sp", "SharePoint", "sharepoint", true),
            integration("cf", "Confluence", "confluence", true)
          ]
        })
      : ok({ items: [] })
  );
  renderInApp(<ImportKnowledgeDialog open onOpenChange={() => {}} />);
  const dialog = await screen.findByRole("dialog", { name: "Importera kunskap" });
  const confluence = await within(dialog).findByRole("radio", { name: /Confluence/ });

  fireEvent.click(confluence);
  expect((confluence as HTMLInputElement).checked).toBe(true);
  fireEvent.click(within(dialog).getByRole("button", { name: "Fortsätt" }));

  expect(
    await screen.findByRole("dialog", { name: "Importera kunskap från Confluence" })
  ).toBeTruthy();
});
