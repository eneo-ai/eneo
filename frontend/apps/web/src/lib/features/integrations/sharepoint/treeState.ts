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

/** True when the item is selected itself or sits under a selected folder or the site root. */
export function isSharePointItemCovered(
  item: SharePointTreeItem,
  selectedKeys: ReadonlySet<string>,
  selectedPaths: readonly string[]
): boolean {
  if (selectedKeys.has(buildSharePointSelectionKey(item))) return true;
  return selectedPaths.some((selectedPath) => isSharePointDescendantPath(item.path, selectedPath));
}
