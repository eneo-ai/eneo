// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const space = vi.hoisted(() => ({ current: null as unknown }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const toast = vi.hoisted(() => ({
  success: vi.fn(),
  info: vi.fn(),
  warning: vi.fn(),
  error: vi.fn()
}));
vi.mock("@/lib/toast", () => ({ toast }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
const jobs = vi.hoisted(() => ({ trackJob: vi.fn() }));
vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => jobs }));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => space.current as Space) };
});

import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { UserIntegration } from "../queries";
import { pendingImports, resetPendingImports } from "../import-completion";
import { ConfluenceImportDialog } from "./confluence-import";
import { SharePointImportDialog } from "./sharepoint-import";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  sessionStorage.clear();
  resetPendingImports();
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
  const job = { id: "job-1", name: "Personal", status: "queued" };
  api.POST.mockImplementation(() => ok(job));
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
  // Its first sync is followed from the job the import returned.
  await waitFor(() => expect(jobs.trackJob).toHaveBeenCalledWith(job));
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
    "Den här ytan har inga aktiverade inbäddningsmodeller"
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
  const created = (index: number, name: string) => ({
    index,
    name,
    status: "created",
    integration_knowledge_id: `ik-${index}`,
    job: { id: `job-${index}`, name, status: "queued" }
  });
  api.POST.mockImplementation(() =>
    ok({
      created_count: 2,
      failed_count: 0,
      items: [created(0, "Policyer"), created(1, "Rutiner")]
    })
  );
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
  // The longest names the server takes.
  expect((groupName as HTMLInputElement).maxLength).toBe(255);
  expect(
    within(dialog).getByRole<HTMLInputElement>("textbox", { name: "Importnamn för Policyer" })
      .maxLength
  ).toBe(255);
  expect(api.POST).not.toHaveBeenCalled();

  fireEvent.change(groupName, { target: { value: "Styrdokument" } });
  fireEvent.click(importButton);
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  expect(api.POST.mock.calls[0]?.[1]).toMatchObject({ body: { wrapper_name: "Styrdokument" } });
  // Every first sync is followed from the job the import returned.
  await waitFor(() =>
    expect(jobs.trackJob).toHaveBeenCalledWith([
      created(0, "Policyer").job,
      created(1, "Rutiner").job
    ])
  );
  // One notice for the import, named for its group, once both have synced.
  expect(pendingImports()).toEqual(
    ["Policyer", "Rutiner"].map((name, index) => ({
      jobId: `job-${index}`,
      knowledgeId: `ik-${index}`,
      name,
      spaceRouteId: "space-1",
      batchId: "job-0",
      batchName: "Styrdokument"
    }))
  );
});

it("SharePoint: tells how many imports failed when only some were queued", async () => {
  space.current = makeSpace();
  api.GET.mockImplementation((path: string) =>
    path.endsWith("/preview/")
      ? ok({
          items: [{ key: "site-1", type: "site", name: "Intranätet", url: "https://sp/intra" }]
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
  api.POST.mockImplementation(() =>
    ok({
      created_count: 1,
      failed_count: 1,
      items: [
        {
          index: 0,
          name: "Policyer",
          status: "created",
          integration_knowledge_id: "ik-1",
          job: { id: "job-0", name: "Policyer", status: "queued" }
        },
        { index: 1, name: "Rutiner", status: "failed", error: "Mappen finns inte" }
      ]
    })
  );
  const onOpenChange = vi.fn();
  renderInApp(
    <SharePointImportDialog
      open
      onOpenChange={onOpenChange}
      onBack={() => {}}
      integration={integration("sharepoint")}
    />
  );
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(await within(dialog).findByRole("button", { name: "Intranätet" }));
  const tree = within(dialog).getByRole("group", { name: "Innehåll" });
  fireEvent.click(await within(tree).findByRole("checkbox", { name: "Policyer" }));
  fireEvent.click(within(tree).getByRole("checkbox", { name: "Rutiner" }));
  fireEvent.change(within(dialog).getByRole("textbox", { name: /^Gruppnamn/ }), {
    target: { value: "Styrdokument" }
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Importera" }));

  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  expect(toast.warning).toHaveBeenCalledWith("1 av 2 importer köades. 1 misslyckades.");
  expect(toast.error).not.toHaveBeenCalled();
});

it("SharePoint: shows why a batch could not start at all, and lets the import be tried again", async () => {
  space.current = makeSpace();
  api.GET.mockImplementation((path: string) =>
    path.endsWith("/preview/")
      ? ok({
          items: [{ key: "site-1", type: "site", name: "Intranätet", url: "https://sp/intra" }]
        })
      : ok({
          items: [
            { id: "f1", name: "Policyer", type: "folder", path: "/Policyer", has_children: true }
          ],
          current_path: "/",
          drive_id: "drive-1"
        })
  );
  api.POST.mockImplementation(() =>
    Promise.resolve({
      error: {
        message: "SharePoint credentials are invalid",
        eneo_error_code: 9007,
        code: "sharepoint_credentials_invalid"
      },
      response: new Response("{}", { status: 400 })
    })
  );
  const onOpenChange = vi.fn();
  renderInApp(
    <SharePointImportDialog
      open
      onOpenChange={onOpenChange}
      onBack={() => {}}
      integration={integration("sharepoint")}
    />
  );
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(await within(dialog).findByRole("button", { name: "Intranätet" }));
  const tree = within(dialog).getByRole("group", { name: "Innehåll" });
  fireEvent.click(await within(tree).findByRole("checkbox", { name: "Policyer" }));
  const importButton = within(dialog).getByRole("button", { name: "Importera" });
  fireEvent.click(importButton);

  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(
      "Microsoft nekade organisationens inloggning till SharePoint. En administratör behöver logga in igen eller uppdatera appens hemlighet.",
      expect.anything()
    )
  );
  expect(onOpenChange).not.toHaveBeenCalled();
  expect(jobs.trackJob).not.toHaveBeenCalled();
  await waitFor(() => expect(importButton.getAttribute("aria-busy")).toBeNull());
  fireEvent.click(importButton);
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(2));
});
