import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { tick, type ComponentProps } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "../../../../app.css";
import * as m from "$lib/paraglide/messages";
import { expectNoAxeViolations } from "$lib/test/axe";
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

describe("SharePoint tree keyboard navigation", () => {
  const policies: SharePointTreeItem = {
    id: "policies",
    name: "Policies",
    type: "folder",
    path: "/Policies",
    has_children: true
  };
  const archive: SharePointTreeItem = {
    id: "archive",
    name: "Archive",
    type: "folder",
    path: "/Archive",
    has_children: true
  };
  const readme: SharePointTreeItem = {
    id: "readme",
    name: "Readme.md",
    type: "file",
    path: "/Readme.md",
    has_children: false
  };
  const child: SharePointTreeItem = {
    id: "p1",
    name: "Policy 1.docx",
    type: "file",
    path: "/Policies/Policy 1.docx",
    has_children: false
  };

  function treeItem(name: string) {
    return page.getByRole("treeitem", { name, exact: true });
  }

  function focused(): string | undefined {
    return (document.activeElement as HTMLElement | null)?.getAttribute("aria-label") ?? undefined;
  }

  beforeEach(() => {
    fetchLibrary.mockReset();
    fetchLibrary.mockImplementation(
      async (path: string, request?: { params?: { query?: { folder_id?: string } } }) => {
        if (!path.endsWith("/tree/")) return { items: [] };
        const folderId = request?.params?.query?.folder_id;
        if (folderId === "policies") return { items: [child] };
        if (folderId === "archive") {
          return { items: [{ ...readme, id: "a1", path: "/Archive/Readme.md" }], truncated: true };
        }
        return { items: [policies, archive, readme] };
      }
    );
  });

  it("keeps one tree item tabbable and moves with the arrows, Home and End", async () => {
    show();
    await expect.element(treeItem("Policies")).toBeVisible();

    expect(treeItem("Policies").element().getAttribute("tabindex")).toBe("0");
    expect(treeItem("Archive").element().getAttribute("tabindex")).toBe("-1");
    const innerControls = Array.from(
      document.querySelectorAll('[role="tree"] [data-slot="checkbox"], [role="tree"] button')
    );
    expect(innerControls.length).toBeGreaterThan(0);
    expect(innerControls.every((el) => el.getAttribute("tabindex") === "-1")).toBe(true);

    (treeItem("Policies").element() as HTMLElement).focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(focused()).toBe("Archive");
    await userEvent.keyboard("{End}");
    expect(focused()).toBe("Readme.md");
    await userEvent.keyboard("{ArrowDown}");
    expect(focused()).toBe("Readme.md");
    await userEvent.keyboard("{Home}");
    expect(focused()).toBe("Policies");
    await userEvent.keyboard("{ArrowUp}");
    expect(focused()).toBe("Policies");
    expect(treeItem("Policies").element().getAttribute("tabindex")).toBe("0");
  });

  it("expands with ArrowRight, moves into and out of the children, collapses with ArrowLeft", async () => {
    show();
    await expect.element(treeItem("Policies")).toBeVisible();
    (treeItem("Policies").element() as HTMLElement).focus();

    await userEvent.keyboard("{ArrowRight}");
    await expect.element(treeItem("Policy 1.docx")).toBeVisible();
    expect(treeItem("Policies").element().getAttribute("aria-expanded")).toBe("true");
    expect(focused()).toBe("Policies");

    await userEvent.keyboard("{ArrowRight}");
    expect(focused()).toBe("Policy 1.docx");
    await userEvent.keyboard("{ArrowLeft}");
    expect(focused()).toBe("Policies");
    await userEvent.keyboard("{ArrowLeft}");
    expect(treeItem("Policies").element().getAttribute("aria-expanded")).toBe("false");
    expect(treeItem("Policy 1.docx").query()).toBeNull();
  });

  it("keeps a focused child as the only tabbable item through a Tab round-trip", async () => {
    show();
    await expect.element(treeItem("Policies")).toBeVisible();
    (treeItem("Policies").element() as HTMLElement).focus();

    await userEvent.keyboard("{ArrowRight}");
    await expect.element(treeItem("Policy 1.docx")).toBeVisible();
    await userEvent.keyboard("{ArrowRight}");
    expect(focused()).toBe("Policy 1.docx");
    expect(treeItem("Policy 1.docx").element().getAttribute("tabindex")).toBe("0");
    expect(treeItem("Policies").element().getAttribute("tabindex")).toBe("-1");
    expect(document.querySelectorAll('[role="treeitem"][tabindex="0"]')).toHaveLength(1);

    await userEvent.keyboard("{Shift>}{Tab}{/Shift}");
    expect(document.activeElement?.closest('[role="tree"]')).toBeNull();
    await userEvent.keyboard("{Tab}");
    expect(focused()).toBe("Policy 1.docx");
  });

  it("exposes the checkbox state on the treeitem, with the parent coverage as its description", async () => {
    show({
      selectedItemKeys: [buildSharePointSelectionKey(policies)],
      selectedPaths: ["/Policies"]
    });
    await expect.element(treeItem("Policies")).toBeVisible();
    (treeItem("Policies").element() as HTMLElement).focus();
    await userEvent.keyboard("{ArrowRight}");
    await expect.element(treeItem("Policy 1.docx")).toBeVisible();

    const parent = treeItem("Policies").element();
    const child = treeItem("Policy 1.docx").element();
    const sibling = treeItem("Readme.md").element();
    expect(parent.getAttribute("aria-checked")).toBe("true");
    expect(child.getAttribute("aria-checked")).toBe("true");
    expect(sibling.getAttribute("aria-checked")).toBe("false");
    expect(parent.hasAttribute("aria-selected")).toBe(false);
    expect(parent.hasAttribute("aria-describedby")).toBe(false);
    const description = document.getElementById(child.getAttribute("aria-describedby") ?? "");
    expect(description?.textContent?.trim()).toBe(m.sharepoint_selected_by_parent());
    expect(page.getByRole("tree").getByRole("checkbox").query()).toBeNull();
    expect(document.querySelector('[role="tree"] [data-slot="checkbox"][title]')).toBeNull();
  });

  it("marks a folder with a selected descendant as mixed", async () => {
    show({ selectedItemKeys: [buildSharePointSelectionKey(child)], selectedPaths: [child.path] });
    await expect.element(treeItem("Policies")).toBeVisible();
    expect(treeItem("Policies").element().getAttribute("aria-checked")).toBe("mixed");
  });

  it("toggles the selection with Space, never for an item covered by its parent", async () => {
    const onToggleSelect = vi.fn();
    show({ onToggleSelect, selectedItemKeys: [buildSharePointSelectionKey(policies)] });
    await expect.element(treeItem("Readme.md")).toBeVisible();

    (treeItem("Readme.md").element() as HTMLElement).focus();
    await userEvent.keyboard(" ");
    expect(onToggleSelect).toHaveBeenCalledWith(expect.objectContaining({ id: "readme" }));

    (treeItem("Policies").element() as HTMLElement).focus();
    await userEvent.keyboard("{Enter}");
    await expect.element(treeItem("Policy 1.docx")).toBeVisible();
    await userEvent.keyboard("{ArrowRight}");
    expect(focused()).toBe("Policy 1.docx");
    await userEvent.keyboard(" ");
    expect(onToggleSelect).toHaveBeenCalledTimes(1);
  });

  it("says when a folder listing was capped", async () => {
    show();
    await expect.element(treeItem("Archive")).toBeVisible();
    expect(page.getByText(m.sharepoint_tree_truncated()).query()).toBeNull();

    (treeItem("Archive").element() as HTMLElement).focus();
    await userEvent.keyboard("{Enter}");

    await expect.element(page.getByText(m.sharepoint_tree_truncated())).toBeVisible();
  });

  it("has no axe violations with an expanded folder", async () => {
    const { container } = show();
    await expect.element(treeItem("Policies")).toBeVisible();
    (treeItem("Policies").element() as HTMLElement).focus();
    await userEvent.keyboard("{ArrowRight}");
    await expect.element(treeItem("Policy 1.docx")).toBeVisible();
    await expectNoAxeViolations(container);
  });
});
