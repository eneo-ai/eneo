// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const space = vi.hoisted(() => ({ current: null as unknown }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => ({ trackJob: vi.fn() }) }));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => space.current as Space) };
});

import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { UserIntegration } from "../queries";
import { ConfluenceImportDialog } from "./confluence-import";
import { SharePointImportDialog } from "./sharepoint-import";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

function integration(type: "confluence" | "sharepoint"): UserIntegration {
  return {
    id: "user-integration-1",
    name: type === "confluence" ? "Confluence" : "SharePoint",
    description: "",
    integration_type: type,
    tenant_integration_id: "tenant-integration-1",
    connected: true
  };
}

const described = (element: HTMLElement) =>
  (element.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent);

it("Confluence: shows a missing space at the list on import, and moves focus to its first", async () => {
  space.current = makeSpace();
  api.GET.mockImplementation(() =>
    ok({
      items: [
        { key: "HR", type: "space", name: "Personal", url: "https://wiki/HR" },
        { key: "IT", type: "space", name: "IT-stöd", url: "https://wiki/IT" }
      ]
    })
  );
  api.POST.mockImplementation(() => ok({}));
  renderInApp(
    <ConfluenceImportDialog
      open
      onOpenChange={() => {}}
      onBack={() => {}}
      integration={integration("confluence")}
    />
  );
  const dialog = await screen.findByRole("dialog", { name: "Importera kunskap från Confluence" });
  const spaces = within(dialog).getByRole("group", { name: "Confluence-ytor" });
  await within(spaces).findByRole("button", { name: "IT-stöd" });
  const importButton = within(dialog).getByRole("button", { name: "Importera yta" });
  expect(importButton.hasAttribute("disabled")).toBe(false);

  fireEvent.click(importButton);

  expect(document.activeElement).toBe(within(spaces).getByRole("button", { name: "IT-stöd" }));
  expect(spaces.getAttribute("aria-invalid")).toBe("true");
  expect(described(spaces)).toEqual(["Välj en Confluence-yta att importera."]);
  expect(api.POST).not.toHaveBeenCalled();

  const personal = within(spaces).getByRole("button", { name: "Personal" });
  fireEvent.click(personal);
  expect(personal.getAttribute("aria-pressed")).toBe("true");
  expect(spaces.getAttribute("aria-invalid")).toBeNull();
  fireEvent.click(importButton);
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  expect(api.POST.mock.calls[0]?.[1]).toMatchObject({
    body: { key: "HR", name: "Personal", embedding_model: { id: "embed-1" } }
  });
});

it("Confluence: moves focus to the warning when the space has no embedding model", async () => {
  space.current = makeSpace({ overrides: { embedding_models: [] } });
  api.GET.mockImplementation(() => ok({ items: [] }));
  renderInApp(
    <ConfluenceImportDialog
      open
      onOpenChange={() => {}}
      onBack={() => {}}
      integration={integration("confluence")}
    />
  );
  const dialog = await screen.findByRole("dialog");

  fireEvent.click(within(dialog).getByRole("button", { name: "Importera yta" }));

  expect(document.activeElement?.textContent).toContain(
    "Denna yta har för närvarande inga inbäddningsmodeller aktiverade"
  );
  expect(api.POST).not.toHaveBeenCalled();
});

it("SharePoint: shows what is missing where it is chosen, one step at a time", async () => {
  space.current = makeSpace();
  api.GET.mockImplementation((path: string) =>
    path.endsWith("/preview/")
      ? ok({
          items: [
            { key: "site-1", type: "site", name: "Intranätet", url: "https://sp/intra" },
            { key: "site-2", type: "site", name: "Ekonomi", url: "https://sp/eko" }
          ]
        })
      : ok({
          items: [
            { id: "f1", name: "Policyer", type: "folder", path: "/Policyer", has_children: true },
            { id: "f2", name: "Rutiner", type: "folder", path: "/Rutiner", has_children: true }
          ],
          current_path: "/",
          drive_id: "drive-1"
        })
  );
  api.POST.mockImplementation(() => ok({ created_count: 2, failed_count: 0 }));
  renderInApp(
    <SharePointImportDialog
      open
      onOpenChange={() => {}}
      onBack={() => {}}
      integration={integration("sharepoint")}
    />
  );
  const dialog = await screen.findByRole("dialog", {
    name: "Importera kunskap från SharePoint / OneDrive"
  });
  const importButton = within(dialog).getByRole("button", { name: "Importera" });
  const sites = within(dialog).getByRole("group", {
    name: "Tillgängliga SharePoint- och OneDrive-källor"
  });
  await within(sites).findByRole("button", { name: "Ekonomi" });

  // No site chosen: at the list, focus on its first site.
  fireEvent.click(importButton);
  expect(document.activeElement).toBe(within(sites).getByRole("button", { name: "Ekonomi" }));
  expect(described(sites)).toEqual(["Välj en SharePoint-webbplats eller OneDrive."]);

  // A site but no content: at the tree, focus on its first checkbox.
  fireEvent.click(within(sites).getByRole("button", { name: "Intranätet" }));
  const tree = within(dialog).getByRole("group", { name: "Innehåll" });
  const policies = await within(tree).findByRole("checkbox", { name: "Policyer" });
  expect(tree.getAttribute("aria-invalid")).toBeNull();
  fireEvent.click(importButton);
  expect(document.activeElement).toBe(within(tree).getAllByRole("checkbox")[0]);
  expect(described(tree)).toEqual(["Välj minst en fil eller mapp att importera."]);

  // Two items need a group name: at its field, which takes focus.
  fireEvent.click(policies);
  fireEvent.click(within(tree).getByRole("checkbox", { name: "Rutiner" }));
  const groupName = within(dialog).getByRole("textbox", { name: /^Gruppnamn/ });
  expect(groupName.getAttribute("aria-invalid")).toBeNull();
  fireEvent.click(importButton);
  expect(document.activeElement).toBe(groupName);
  expect(groupName.getAttribute("aria-invalid")).toBe("true");
  expect(described(groupName)).toEqual([
    "Ange gruppnamn för att kunna importera.",
    "Gruppnamn krävs när du importerar flera mappar/filer samtidigt."
  ]);
  expect(within(dialog).getByRole("textbox", { name: "Importnamn för Policyer" })).toBeTruthy();
  expect(api.POST).not.toHaveBeenCalled();

  fireEvent.change(groupName, { target: { value: "Styrdokument" } });
  fireEvent.click(importButton);
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  expect(api.POST.mock.calls[0]?.[1]).toMatchObject({ body: { wrapper_name: "Styrdokument" } });
});
