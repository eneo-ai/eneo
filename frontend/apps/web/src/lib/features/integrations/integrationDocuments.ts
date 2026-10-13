import type { SourceMetadataEntry } from "$lib/features/knowledge/sourceMetadata";

// Response shapes of the integration document endpoints; they mirror the
// backend's IntegrationDocumentsPage and IntegrationSkippedDocuments models.
export type IntegrationDocument = {
  id: string;
  title: string;
  /** Folder path below the imported folder; empty for the imported folder itself. */
  relative_path: string;
  url: string | null;
  size: number;
  updated_at: string | null;
  source_metadata?: SourceMetadataEntry[] | null;
};

export type IntegrationDocumentsPage = {
  items: IntegrationDocument[];
  total_count: number;
  limit: number;
  offset: number;
  total_size: number;
};

export type IntegrationDocumentSort = "name" | "path" | "size" | "updated_at";
export type IntegrationDocumentOrder = "asc" | "desc";

export type IntegrationDocumentsQuery = {
  q: string;
  sort: IntegrationDocumentSort;
  order: IntegrationDocumentOrder;
  limit: number;
  offset: number;
};

export const INTEGRATION_DOCUMENTS_PAGE_SIZE = 50;

export const DEFAULT_INTEGRATION_DOCUMENTS_QUERY: IntegrationDocumentsQuery = {
  q: "",
  sort: "path",
  order: "asc",
  limit: INTEGRATION_DOCUMENTS_PAGE_SIZE,
  offset: 0
};

export type IntegrationSkippedDocument = { file: string; reason: string };

export type IntegrationSkippedDocuments = {
  items: IntegrationSkippedDocument[];
  /** Every skipped file, also those the capped `items` list leaves out. */
  total: number;
  truncated: boolean;
  synced_at: string | null;
};

export type IntegrationDocumentsTab = "documents" | "skipped";

export function integrationDocumentsHref(
  spaceRouteId: string,
  knowledgeId: string,
  tab?: IntegrationDocumentsTab
): string {
  const base = `/spaces/${spaceRouteId}/knowledge/integrations/${knowledgeId}`;
  return tab === "skipped" ? `${base}?tab=skipped` : base;
}

export type SkippedReasonGroup = { reason: string; files: string[] };

/** Skipped files by reason, largest group first; equal groups keep their first appearance. */
export function groupSkippedByReason(items: IntegrationSkippedDocument[]): SkippedReasonGroup[] {
  const groups = new Map<string, SkippedReasonGroup>();
  for (const item of items) {
    const reason = item.reason.trim();
    const group = groups.get(reason);
    if (group) group.files.push(item.file);
    else groups.set(reason, { reason, files: [item.file] });
  }
  return [...groups.values()].sort((a, b) => b.files.length - a.files.length);
}

/** How many skipped files the capped list leaves out. */
export function skippedDocumentsNotListed(skipped: IntegrationSkippedDocuments): number {
  return skipped.truncated ? Math.max(0, skipped.total - skipped.items.length) : 0;
}

export type PageRange = { from: number; to: number; total: number };

/** The 1-based positions of the page's rows, for "Showing 1–50 of 312". */
export function documentsPageRange(page: {
  items: unknown[];
  offset: number;
  total_count: number;
}): PageRange {
  const total = Math.max(0, page.total_count);
  if (page.items.length === 0 || total === 0) return { from: 0, to: 0, total };
  const from = page.offset + 1;
  return { from, to: Math.min(total, page.offset + page.items.length), total };
}

/** The offset of the last page that still holds a row; 0 when there is none. */
export function lastPageOffset(page: { total_count: number }, limit: number): number {
  const total = Math.max(0, page.total_count);
  if (total === 0 || limit <= 0) return 0;
  return Math.floor((total - 1) / limit) * limit;
}

/** The sort after clicking a column: a new column sorts ascending, the current one flips. */
export function toggleDocumentsSort(
  query: IntegrationDocumentsQuery,
  sort: IntegrationDocumentSort
): IntegrationDocumentsQuery {
  const order: IntegrationDocumentOrder =
    query.sort === sort ? (query.order === "asc" ? "desc" : "asc") : "asc";
  return { ...query, sort, order, offset: 0 };
}
