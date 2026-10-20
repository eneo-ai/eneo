import type { components } from "@eneo/eneo-js";

export type IntegrationDocument = components["schemas"]["IntegrationDocumentItem"];
export type IntegrationDocumentsPage = components["schemas"]["IntegrationDocumentsPage"];

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
/** The API answers 422 to a longer `q`. */
export const INTEGRATION_DOCUMENTS_QUERY_MAX_LENGTH = 200;

export const DEFAULT_INTEGRATION_DOCUMENTS_QUERY: IntegrationDocumentsQuery = {
  q: "",
  sort: "path",
  order: "asc",
  limit: INTEGRATION_DOCUMENTS_PAGE_SIZE,
  offset: 0
};

/** What a documents view starts from when the first page could not be listed. */
export function emptyDocumentsPage(): IntegrationDocumentsPage {
  return {
    items: [],
    total_count: 0,
    limit: INTEGRATION_DOCUMENTS_PAGE_SIZE,
    offset: 0,
    total_size: 0
  };
}

export type IntegrationSkippedDocument = components["schemas"]["IntegrationSkippedDocument"];
export type IntegrationSkippedDocuments = components["schemas"]["IntegrationSkippedDocuments"];

/** An item's page; an item imported with others redirects to its folder on the wrapper's page. */
export function integrationDocumentsHref(
  spaceRouteId: string,
  knowledgeId: string,
  tab?: "problems"
): string {
  const base = `/spaces/${spaceRouteId}/knowledge/integrations/${knowledgeId}`;
  return tab ? `${base}?tab=${tab}` : base;
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
