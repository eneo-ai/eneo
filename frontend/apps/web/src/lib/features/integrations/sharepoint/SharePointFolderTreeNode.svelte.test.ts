import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import * as m from "$lib/paraglide/messages";
import SharePointFolderTreeNode from "./SharePointFolderTreeNode.svelte";
import { createSharePointTreeNode, type SharePointTreeItem } from "./treeState";

const file = (overrides: Partial<SharePointTreeItem> = {}): SharePointTreeItem => ({
  id: "file-1",
  name: "Rutin för larm.docx",
  type: "file",
  path: "/Rutiner/Rutin för larm.docx",
  has_children: false,
  size: 12_000,
  ...overrides
});

function renderNode(item: SharePointTreeItem, query = "") {
  return render(SharePointFolderTreeNode, {
    node: createSharePointTreeNode(item),
    query,
    selectedItemKeySet: new Set<string>(),
    selectedPaths: [],
    onToggleSelect: vi.fn(),
    onToggleExpanded: vi.fn(),
    onRetryLoad: vi.fn()
  });
}

describe("SharePointFolderTreeNode document properties", () => {
  it("shows a file's library columns under its name", async () => {
    renderNode(
      file({
        source_metadata: [
          { name: "Dokumenttyp", label: "Dokumenttyp", value: "Rutin", kind: "choice" },
          { name: "Extern", label: "Extern publicering", value: "false", kind: "boolean" }
        ]
      })
    );

    await expect.element(page.getByText("Rutin för larm.docx")).toBeVisible();
    await expect.element(page.getByText("Dokumenttyp:")).toBeVisible();
    await expect.element(page.getByText("Rutin", { exact: true })).toBeVisible();
    await expect.element(page.getByText("Extern publicering:")).toBeVisible();
    await expect.element(page.getByText(m.no(), { exact: true })).toBeVisible();
  });

  it("shows nothing extra for a file without columns", async () => {
    renderNode(file());

    await expect.element(page.getByText("Rutin för larm.docx")).toBeVisible();
    expect(page.getByText("Dokumenttyp:").query()).toBeNull();
  });

  it("marks the part of a name or property that the search hit", async () => {
    renderNode(
      file({
        source_metadata: [
          { name: "Dokumenttyp", label: "Dokumenttyp", value: "Rutin", kind: "choice" }
        ]
      }),
      "rutin"
    );

    const marks = document.querySelectorAll("mark");
    expect([...marks].map((mark) => mark.textContent)).toEqual(["Rutin", "Rutin"]);
    await expect.element(page.getByText("Rutin för larm.docx")).toBeVisible();
  });
});
