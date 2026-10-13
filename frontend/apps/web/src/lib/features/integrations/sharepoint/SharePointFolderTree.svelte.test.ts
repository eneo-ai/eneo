import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { tick, type ComponentProps } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as m from "$lib/paraglide/messages";
import { buildSharePointSelectionKey } from "./selectionKey";
import type { SharePointTreeItem } from "./treeState";

type Response = { items: SharePointTreeItem[]; truncated?: boolean };
const fetchLibrary = vi.hoisted(() => vi.fn<(path: string) => Promise<Response>>());
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ client: { fetch: fetchLibrary } })
}));

import SharePointFolderTree from "./SharePointFolderTree.svelte";

const hit: SharePointTreeItem = {
  id: "policy",
  name: "Policy.docx",
  type: "file",
  path: "/Policies/Policy.docx",
  has_children: false,
  source_metadata: []
};

function show(overrides: Partial<ComponentProps<typeof SharePointFolderTree>> = {}) {
  return render(SharePointFolderTree, {
    userIntegrationId: "integration-1",
    spaceId: "space-1",
    driveId: "drive-1",
    siteName: "Library",
    isOneDrive: false,
    onToggleSelect: vi.fn(),
    onSelectMany: vi.fn(),
    onDeselectMany: vi.fn(),
    ...overrides
  });
}

async function enterSearch(text: string) {
  const input = document.querySelector<HTMLInputElement>('input[type="search"]');
  if (!input) throw new Error("Library search field is missing");
  input.value = text;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await tick();
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("SharePoint library search state", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    fetchLibrary.mockReset();
    fetchLibrary.mockImplementation(async (path) => ({
      items: path.endsWith("/search/") ? [hit] : []
    }));
  });
  afterEach(() => vi.useRealTimers());

  it("removes selectable old results immediately while the next request is debounced", async () => {
    show();
    await tick();
    await enterSearch("policy");
    await vi.advanceTimersByTimeAsync(300);
    await tick();
    expect(
      page.getByRole("checkbox", { name: m.sharepoint_select_item({ name: hit.name }) }).query()
    ).not.toBeNull();

    await enterSearch("new query");

    expect(
      page.getByRole("checkbox", { name: m.sharepoint_select_item({ name: hit.name }) }).query()
    ).toBeNull();
    expect(
      page.getByRole("button", { name: m.sharepoint_select_all_matches({ count: "1" }) }).query()
    ).toBeNull();
    expect(fetchLibrary.mock.calls.filter(([path]) => path.endsWith("/search/"))).toHaveLength(1);
  });

  it("ignores an older response that arrives before the new debounce expires", async () => {
    const older = deferred<Response>();
    fetchLibrary.mockImplementation((path) =>
      path.endsWith("/search/") ? older.promise : Promise.resolve({ items: [] })
    );
    show();
    await tick();
    await enterSearch("old");
    await vi.advanceTimersByTimeAsync(300);
    await enterSearch("new");

    older.resolve({ items: [hit] });
    await older.promise;
    await tick();

    expect(
      page.getByRole("checkbox", { name: m.sharepoint_select_item({ name: hit.name }) }).query()
    ).toBeNull();
    expect(fetchLibrary.mock.calls.filter(([path]) => path.endsWith("/search/"))).toHaveLength(1);
  });

  it("explains and disables bulk selection when every hit is covered by a folder", async () => {
    const onDeselectMany = vi.fn();
    show({ selectedPaths: ["/Policies"], onDeselectMany });
    await tick();
    await enterSearch("policy");
    await vi.advanceTimersByTimeAsync(300);
    await tick();

    const button = page
      .getByRole("button", { name: m.sharepoint_selected_by_parent() })
      .element() as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    button.click();
    expect(onDeselectMany).not.toHaveBeenCalled();
  });

  it("bulk deselection removes direct hits while preserving parent coverage", async () => {
    const direct: SharePointTreeItem = {
      ...hit,
      id: "direct",
      name: "Direct.docx",
      path: "/Direct.docx"
    };
    fetchLibrary.mockImplementation(async (path) => ({
      items: path.endsWith("/search/") ? [hit, direct] : []
    }));
    const onDeselectMany = vi.fn();
    show({
      selectedPaths: ["/Policies", direct.path],
      selectedItemKeys: [buildSharePointSelectionKey(direct)],
      onDeselectMany
    });
    await tick();
    await enterSearch("policy");
    await vi.advanceTimersByTimeAsync(300);
    await tick();

    (
      page
        .getByRole("button", { name: m.sharepoint_deselect_all_matches() })
        .element() as HTMLButtonElement
    ).click();

    expect(onDeselectMany).toHaveBeenCalledWith([direct]);
  });
});
