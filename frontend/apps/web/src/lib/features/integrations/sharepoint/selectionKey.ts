export type SharePointSelectableType = "file" | "folder" | "site_root";

export type SharePointSelectable = {
  id?: string | null;
  type: SharePointSelectableType;
  path?: string | null;
  name?: string | null;
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

export function buildSharePointSelectionKey(item: SharePointSelectable): string {
  if (item.type === "site_root") {
    return "site_root:root:/";
  }

  const normalizedPath = normalizeSharePointPath(item.path);
  const rawId = (item.id ?? "").trim();
  const normalizedName = (item.name ?? "").trim();
  const identity = rawId.length > 0 ? rawId : normalizedPath;
  return `${item.type}:${identity}:${normalizedPath}:${normalizedName}`;
}
