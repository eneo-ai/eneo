/**
 * Pure selection logic for the SharePoint import dialog (unit-tested).
 * Ported from the Svelte app's selectionKey.ts + SharepointImportDialog
 * dedupe logic.
 */

export type SharePointSelectableType = "file" | "folder" | "site_root";

export type SelectedTreeItem = {
  id: string;
  name: string;
  type: SharePointSelectableType;
  path: string;
  web_url?: string | null;
  size?: number | null;
};

export type SelectedImportItem = {
  selectionKey: string;
  item: SelectedTreeItem;
  importName: string;
};

export function normalizeSharePointPath(path: string | null | undefined): string {
  if (!path) return "/";
  const collapsed = path.replace(/\/+/g, "/");
  const withLeadingSlash = collapsed.startsWith("/") ? collapsed : `/${collapsed}`;
  if (withLeadingSlash.length > 1 && withLeadingSlash.endsWith("/")) {
    return withLeadingSlash.slice(0, -1);
  }
  return withLeadingSlash;
}

export function buildSelectionKey(item: {
  id?: string | null;
  type: SharePointSelectableType;
  path?: string | null;
  name?: string | null;
}): string {
  if (item.type === "site_root") {
    return "site_root:root:/";
  }
  const normalizedPath = normalizeSharePointPath(item.path);
  const rawId = (item.id ?? "").trim();
  const normalizedName = (item.name ?? "").trim();
  const identity = rawId.length > 0 ? rawId : normalizedPath;
  return `${item.type}:${identity}:${normalizedPath}:${normalizedName}`;
}

function isDescendantPath(path: string, ancestorPath: string): boolean {
  const normalizedPath = normalizeSharePointPath(path);
  const normalizedAncestor = normalizeSharePointPath(ancestorPath);
  if (normalizedAncestor === "/") {
    return normalizedPath !== "/";
  }
  return normalizedPath.startsWith(`${normalizedAncestor}/`);
}

/**
 * Drops selections already covered by a selected ancestor folder (or the
 * site root): importing the parent includes them. Excluded entries stay in
 * the UI list, flagged via `excludedKeys`.
 */
export function dedupeNestedSelection(entries: SelectedImportItem[]): {
  effectiveEntries: SelectedImportItem[];
  excludedKeys: Set<string>;
} {
  const sorted = [...entries].sort(
    (a, b) =>
      normalizeSharePointPath(a.item.path).length - normalizeSharePointPath(b.item.path).length
  );

  const effectiveEntries: SelectedImportItem[] = [];
  const excludedKeys = new Set<string>();

  for (const entry of sorted) {
    const blockedByParent = effectiveEntries.some((existing) => {
      if (existing.selectionKey === entry.selectionKey) return false;
      if (existing.item.type !== "folder" && existing.item.type !== "site_root") return false;
      return isDescendantPath(entry.item.path, existing.item.path);
    });

    if (blockedByParent) {
      excludedKeys.add(entry.selectionKey);
      continue;
    }
    effectiveEntries.push(entry);
  }

  return { effectiveEntries, excludedKeys };
}

export type ImportSite = {
  key: string;
  name: string;
  url: string;
  type: string;
};

export type BatchImportItem = {
  key?: string | null;
  name: string;
  url: string;
  folder_id?: string | null;
  folder_path?: string | null;
  selected_item_type?: string | null;
  resource_type?: string | null;
};

/** Request items for the batch import endpoint; site_root rows import the whole site. */
export function buildBatchItems(
  site: ImportSite,
  entries: SelectedImportItem[]
): BatchImportItem[] {
  const resourceType = site.type === "onedrive" ? "onedrive" : "site";
  return entries.map((entry) => {
    const trimmedName = entry.importName.trim();
    const name = trimmedName.length > 0 ? trimmedName : entry.item.name;

    if (entry.item.type === "site_root") {
      return {
        key: site.key,
        name,
        url: site.url,
        selected_item_type: "site_root",
        resource_type: resourceType
      };
    }
    return {
      key: site.key,
      name,
      url: entry.item.web_url ?? "",
      folder_id: entry.item.id,
      folder_path: entry.item.path,
      selected_item_type: entry.item.type,
      resource_type: resourceType
    };
  });
}
