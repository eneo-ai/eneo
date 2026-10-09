import type { SharePointFilterColumn } from "./treeState";

export type ActiveFacet = { column: SharePointFilterColumn; value: string };

/** The chosen filters in column order; "" and unknown columns are not filters. */
export function activeFacets(
  columns: SharePointFilterColumn[],
  facets: Record<string, string>
): ActiveFacet[] {
  return columns
    .map((column) => ({ column, value: facets[column.name] ?? "" }))
    .filter((entry) => entry.value !== "");
}

/** The facet value as people read it; yes/no columns are stored as true/false. */
export function facetValueLabel(
  column: SharePointFilterColumn,
  value: string,
  labels: { yes: string; no: string }
): string {
  if (column.kind === "boolean") return value === "true" ? labels.yes : labels.no;
  return value;
}

/** `facets` with one column set, or cleared when `value` is empty. */
export function withFacet(
  facets: Record<string, string>,
  name: string,
  value: string
): Record<string, string> {
  const next = { ...facets, [name]: value };
  if (!value) delete next[name];
  return next;
}
