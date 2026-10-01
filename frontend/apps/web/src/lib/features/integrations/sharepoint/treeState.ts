import { normalizeSharePointPath } from "./selectionKey";
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
