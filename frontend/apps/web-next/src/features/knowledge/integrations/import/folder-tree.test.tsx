// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { SharePointFolderTree } from "./folder-tree";
import { buildSelectionKey, type SelectedTreeItem } from "./selection";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
afterEach(() => {
  cleanup();
  api.GET.mockReset();
});

const file: SelectedTreeItem = {
  id: "report",
  name: "Report.pdf",
  type: "file",
  path: "/Docs/Report.pdf"
};
const folder: SelectedTreeItem = { id: "docs", name: "Docs", type: "folder", path: "/Docs" };
const columns = [{ name: "Department", label: "Avdelning", kind: "choice", choices: ["HR", "IT"] }];
const reply = (items: SelectedTreeItem[], extra = {}) =>
  Promise.resolve({
    data: { items, drive_id: "drive", current_path: "/", ...extra },
    response: new Response("{}")
  });
type Request = {
  params: { query: { q?: string; filter?: string[]; folder_id?: string } };
  signal: AbortSignal;
};
function show(selected: SelectedTreeItem[] = [], type = "site") {
  const props = {
    userIntegrationId: "connection",
    spaceId: "space",
    site: { key: "site", name: "Intranätet", type },
    selectedKeys: new Set(selected.map(buildSelectionKey)),
    selectedPaths: selected.filter((item) => item.type !== "file").map((item) => item.path),
    onToggleSelect: vi.fn(),
    onSelectMany: vi.fn(),
    onDeselectMany: vi.fn()
  };
  const view = renderInApp(<SharePointFolderTree {...props} />);
  return { ...props, ...view };
}

it("searches the entire library and hides stale selections immediately, cancelling an older request", async () => {
  let pendingSignal: AbortSignal | undefined;
  api.GET.mockImplementation((path: string, options: Request) => {
    if (path.endsWith("/tree/")) return reply([folder], { columns });
    if (options.params.query.q === "waiting") {
      pendingSignal = options.signal;
      return new Promise(() => {});
    }
    return reply([file], { truncated: true });
  });
  const props = show();
  await screen.findByRole("checkbox", { name: "Docs" });
  const search = screen.getByRole("searchbox", { name: "Sök filer och egenskaper i Intranätet" });
  fireEvent.change(search, { target: { value: "report" } });
  expect(screen.queryByRole("checkbox", { name: "Docs" })).toBeNull();
  await screen.findByRole("checkbox", { name: "Report.pdf" });
  expect(screen.getByText(/Sökningen är ofullständig/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Välj alla träffar (1)" }));
  expect(props.onSelectMany).toHaveBeenCalledWith([file]);
  const searchCall = api.GET.mock.calls.find(([path]) => path.endsWith("/search/"));
  expect(searchCall?.[1].params.query).toMatchObject({
    space_id: "space",
    site_id: "site",
    q: "report"
  });
  expect(searchCall?.[1].params.query.folder_id).toBeUndefined();
  fireEvent.change(search, { target: { value: "waiting" } });
  expect(screen.queryByRole("checkbox", { name: "Report.pdf" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Välj alla träffar/ })).toBeNull();
  await waitFor(() => expect(pendingSignal).toBeDefined());
  fireEvent.change(search, { target: { value: "new" } });
  await waitFor(() => expect(pendingSignal?.aborted).toBe(true));
});

it("keeps root facets while browsing and sends removable server filters", async () => {
  api.GET.mockImplementation((path: string, options: Request) =>
    path.endsWith("/search/")
      ? reply([file])
      : options.params.query.folder_id
        ? reply([file])
        : reply([folder], { columns, truncated: true })
  );
  show();
  await screen.findByRole("checkbox", { name: "Docs" });
  expect(screen.getByText(/Alla objekt i mappen visas inte/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Öppna mapp" }));
  await screen.findByRole("checkbox", { name: "Report.pdf" });
  fireEvent.click(screen.getByRole("button", { name: /Filtrera på dokumentegenskaper, 0 aktiva/ }));
  fireEvent.click(screen.getByRole("combobox", { name: "Avdelning" }));
  fireEvent.click(await screen.findByRole("option", { name: "HR" }));
  await waitFor(() =>
    expect(
      api.GET.mock.calls.some(
        ([path, options]) =>
          path.endsWith("/search/") && options.params.query.filter?.includes("Department:HR")
      )
    ).toBe(true)
  );
  fireEvent.click(screen.getByRole("button", { name: "Ta bort filtret Avdelning" }));
  expect(screen.queryByRole("button", { name: "Ta bort filtret Avdelning" })).toBeNull();
});

it("marks covered descendants as selected and excludes them from bulk selection", async () => {
  api.GET.mockImplementation(() => reply([file]));
  const props = show([folder]);
  const checkbox = await screen.findByRole("checkbox", { name: "Report.pdf" });
  expect((checkbox as HTMLInputElement).checked).toBe(true);
  expect(checkbox.getAttribute("aria-disabled")).toBe("true");
  fireEvent.click(checkbox);
  expect(props.onToggleSelect).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "report" } });
  await screen.findByRole("checkbox", { name: "Report.pdf" });
  expect(screen.queryByRole("button", { name: /Välj alla träffar/ })).toBeNull();
});

it("shows a failed search with retry instead of an empty library", async () => {
  let failed = true;
  api.GET.mockImplementation((path: string) =>
    path.endsWith("/search/") && failed
      ? Promise.resolve({
          error: { message: "Unavailable" },
          response: new Response("", { status: 503 })
        })
      : reply([file])
  );
  show();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "report" } });
  const retry = await screen.findByRole("button", { name: /Försök igen/ });
  expect(
    screen
      .getAllByRole("alert")
      .some((alert) => alert.textContent?.includes("Sökningen kunde inte genomföras"))
  ).toBe(true);
  failed = false;
  fireEvent.click(retry);
  await screen.findByRole("checkbox", { name: "Report.pdf" });
});

it("searches OneDrive with its drive scope and deselects only the visible matches", async () => {
  api.GET.mockImplementation(() => reply([file]));
  const props = show([file], "onedrive");
  await screen.findByRole("checkbox", { name: "Report.pdf" });
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "report" } });
  fireEvent.click(await screen.findByRole("button", { name: "Avmarkera träffarna" }));
  expect(props.onDeselectMany).toHaveBeenCalledWith([file]);
  const request = api.GET.mock.calls.find(([path]) => path.endsWith("/search/"))?.[1];
  expect(request.params.query).toMatchObject({ drive_id: "site", site_id: undefined });
  await expectNoAxeViolations(props.container);
});
