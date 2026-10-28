import { buildSharePointSelectionKey, normalizeSharePointPath } from "./selectionKey";
import type { components } from "@eneo/eneo-js";
import type { SourceMetadataEntry } from "$lib/features/knowledge/sourceMetadata";

/** A library column a person can filter on without typing: yes/no or a fixed choice. */
export type SharePointFilterColumn = components["schemas"]["SharePointFilterColumn"];

export type SharePointTreeItem = {
  id: string;
  name: string;
  type: "file" | "folder" | "site_root";
  path: string;
  web_url?: string;
  has_children: boolean;
  size?: number;
  modified?: string;
  /** Library columns a file carries; what an import stores as document properties. */
  source_metadata?: SourceMetadataEntry[];
};

export type SharePointTreeNode = SharePointTreeItem & {
  children: SharePointTreeNode[] | null;
  expanded: boolean;
  loading: boolean;
  loadError: boolean;
  /** The listing of this folder was capped by the API; search reaches the rest. */
  childrenTruncated: boolean;
};

export function createSharePointTreeNode(item: SharePointTreeItem): SharePointTreeNode {
  return {
    ...item,
    children: item.type === "folder" ? null : [],
    expanded: false,
    loading: false,
    loadError: false,
    childrenTruncated: false
  };
}

/** One rendered tree item, in document order, with what keyboard handling needs. */
export type SharePointTreeRow = {
  node: SharePointTreeNode;
  key: string;
  parentKey: string | null;
  /** Covered by a selected ancestor or the site root: its checkbox is disabled. */
  parentSelected: boolean;
};

export function flattenVisibleSharePointTree(
  roots: readonly SharePointTreeNode[],
  selectedKeys: ReadonlySet<string>,
  siteRootSelected: boolean
): SharePointTreeRow[] {
  const rows: SharePointTreeRow[] = [];
  const visit = (node: SharePointTreeNode, parentKey: string | null, parentSelected: boolean) => {
    const key = buildSharePointSelectionKey(node);
    rows.push({ node, key, parentKey, parentSelected });
    if (node.type !== "folder" || !node.expanded) return;
    const selected = parentSelected || selectedKeys.has(key);
    for (const child of node.children ?? []) visit(child, key, selected);
  };
  for (const root of roots) visit(root, null, siteRootSelected);
  return rows;
}

export type SharePointTreeKeyAction =
  | { type: "focus"; key: string }
  | { type: "expand"; node: SharePointTreeNode }
  | { type: "collapse"; node: SharePointTreeNode }
  | { type: "toggleSelect"; node: SharePointTreeNode };

function expandable(node: SharePointTreeNode): boolean {
  return node.type === "folder" && node.has_children;
}

/** The WAI-ARIA tree keyboard pattern over the visible rows; null leaves the key to the browser. */
export function resolveSharePointTreeKey(
  rows: readonly SharePointTreeRow[],
  currentKey: string,
  key: string
): SharePointTreeKeyAction | null {
  const index = rows.findIndex((row) => row.key === currentKey);
  if (index === -1) return null;
  const row = rows[index];
  const focus = (target: SharePointTreeRow | undefined) =>
    target && target.key !== currentKey ? { type: "focus" as const, key: target.key } : null;

  switch (key) {
    case "ArrowDown":
      return focus(rows[index + 1]);
    case "ArrowUp":
      return focus(rows[index - 1]);
    case "Home":
      return focus(rows[0]);
    case "End":
      return focus(rows[rows.length - 1]);
    case "ArrowRight": {
      if (!expandable(row.node)) return null;
      if (!row.node.expanded) return { type: "expand", node: row.node };
      const firstChild = rows[index + 1];
      return firstChild?.parentKey === row.key ? focus(firstChild) : null;
    }
    case "ArrowLeft": {
      if (expandable(row.node) && row.node.expanded) return { type: "collapse", node: row.node };
      return row.parentKey === null ? null : focus(rows.find((r) => r.key === row.parentKey));
    }
    case " ":
      return row.parentSelected ? null : { type: "toggleSelect", node: row.node };
    case "Enter":
      if (!expandable(row.node)) return null;
      return row.node.expanded
        ? { type: "collapse", node: row.node }
        : { type: "expand", node: row.node };
    default:
      return null;
  }
}

export function isSharePointDescendantPath(path: string, ancestorPath: string): boolean {
  const normalizedPath = normalizeSharePointPath(path);
  const normalizedAncestor = normalizeSharePointPath(ancestorPath);
  if (normalizedAncestor === "/") return normalizedPath !== "/";
  return normalizedPath.startsWith(`${normalizedAncestor}/`);
}

export function hasSelectedSharePointDescendant(
  selectedPaths: readonly string[],
  ancestorPath: string
): boolean {
  return selectedPaths.some((path) => isSharePointDescendantPath(path, ancestorPath));
}

/** The query as compared: trimmed and case-folded. Empty means "not searching". */
export function normalizeSharePointTreeQuery(query: string): string {
  return query.trim().toLowerCase();
}

/** True when the item is selected itself or sits under a selected folder or the site root. */
export function isSharePointItemCovered(
  item: SharePointTreeItem,
  selectedKeys: ReadonlySet<string>,
  selectedPaths: readonly string[]
): boolean {
  if (selectedKeys.has(buildSharePointSelectionKey(item))) return true;
  return selectedPaths.some((selectedPath) => isSharePointDescendantPath(item.path, selectedPath));
}
