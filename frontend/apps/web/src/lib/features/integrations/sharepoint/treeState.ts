import { buildSharePointSelectionKey, normalizeSharePointPath } from "./selectionKey";
import type { SourceMetadataEntry } from "$lib/features/knowledge/sourceMetadata";

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
};

export function createSharePointTreeNode(item: SharePointTreeItem): SharePointTreeNode {
  return {
    ...item,
    children: item.type === "folder" ? null : [],
    expanded: false,
    loading: false,
    loadError: false
  };
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

/** True when the node's own name or one of its document properties contains the query. */
export function sharePointTreeItemMatches(item: SharePointTreeItem, query: string): boolean {
  if (!query) return true;
  if (item.name.toLowerCase().includes(query)) return true;
  return (item.source_metadata ?? []).some((entry) => {
    if (entry.label.toLowerCase().includes(query)) return true;
    const values = Array.isArray(entry.value) ? entry.value : [entry.value];
    return values.some((value) => value.toLowerCase().includes(query));
  });
}

/**
 * True when the node matches itself or through a loaded descendant. Folders
 * whose contents have not been fetched cannot match through their contents;
 * the tree says so beside the search field.
 */
export function sharePointTreeNodeVisible(node: SharePointTreeNode, query: string): boolean {
  if (!query) return true;
  if (sharePointTreeItemMatches(node, query)) return true;
  return (node.children ?? []).some((child) => sharePointTreeNodeVisible(child, query));
}

/** True when a loaded descendant matches, so the folder should open during a search. */
export function sharePointTreeHasMatchingDescendant(
  node: SharePointTreeNode,
  query: string
): boolean {
  if (!query) return false;
  return (node.children ?? []).some((child) => sharePointTreeNodeVisible(child, query));
}

/**
 * `text` cut into the parts that match the query and the parts that do not,
 * in order, so a renderer can wrap the matches. Case-insensitive, every
 * occurrence; one segment with `match: false` when there is no query.
 */
export function splitSharePointMatches(
  text: string,
  query: string
): { text: string; match: boolean }[] {
  if (!query || !text) return [{ text, match: false }];
  const segments: { text: string; match: boolean }[] = [];
  const lower = text.toLowerCase();
  let from = 0;
  for (;;) {
    const at = lower.indexOf(query, from);
    if (at === -1) break;
    if (at > from) segments.push({ text: text.slice(from, at), match: false });
    segments.push({ text: text.slice(at, at + query.length), match: true });
    from = at + query.length;
  }
  if (from < text.length) segments.push({ text: text.slice(from), match: false });
  return segments;
}

/**
 * The loaded nodes that match the query, as the smallest set that covers them:
 * a matching folder stands for its contents, so matches below it are left out.
 * Order follows the tree.
 */
export function collectSharePointTreeMatches(
  nodes: readonly SharePointTreeNode[],
  query: string
): SharePointTreeItem[] {
  if (!query) return [];
  const matches: SharePointTreeItem[] = [];
  for (const node of nodes) {
    if (sharePointTreeItemMatches(node, query)) {
      matches.push(node);
      continue;
    }
    matches.push(...collectSharePointTreeMatches(node.children ?? [], query));
  }
  return matches;
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

/** Loaded files and folders that match the query themselves. */
export function countSharePointTreeMatches(
  nodes: readonly SharePointTreeNode[],
  query: string
): number {
  if (!query) return 0;
  let count = 0;
  for (const node of nodes) {
    if (sharePointTreeItemMatches(node, query)) count += 1;
    count += countSharePointTreeMatches(node.children ?? [], query);
  }
  return count;
}
