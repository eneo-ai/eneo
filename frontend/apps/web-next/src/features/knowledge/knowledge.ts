import { infiniteQueryOptions, queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { cursorPagination } from "@/lib/api/pagination";

export type Collection = Schema<"CollectionPublic">;
export type Website = Schema<"WebsitePublic">;
export type CrawlRun = NonNullable<Website["latest_crawl"]>;
export type CrawlFailure = Schema<"CrawlResourceFailurePublic">;
export type CrawlFailurePage = Schema<"CrawlFailurePagePublic">;
export type InfoBlob = Schema<"InfoBlobPublicNoText">;
export type EmbeddingModel = Schema<"EmbeddingModelPublic">;
export type IntegrationKnowledge = Schema<"IntegrationKnowledgePublic">;

export function formatWebsiteName(website: { url: string; name?: string | null }): string {
  if (website.name) return website.name;
  return website.url.split("//")[1] ?? website.url;
}

export function collectionQueryOptions(api: EneoClient, collectionId: string) {
  return queryOptions({
    queryKey: ["collections", collectionId],
    queryFn: () =>
      unwrap(api.GET("/api/v1/groups/{id}/", { params: { path: { id: collectionId } } }))
  });
}

export function collectionBlobsQueryOptions(api: EneoClient, collectionId: string) {
  return queryOptions({
    queryKey: ["collections", collectionId, "info-blobs"],
    queryFn: async (): Promise<InfoBlob[]> => {
      const page = await unwrap(
        api.GET("/api/v1/groups/{id}/info-blobs/", { params: { path: { id: collectionId } } })
      );
      return page.items;
    }
  });
}

export function websiteQueryOptions(api: EneoClient, websiteId: string) {
  return queryOptions({
    queryKey: ["websites", websiteId],
    queryFn: () =>
      unwrap(api.GET("/api/v1/websites/{id}/", { params: { path: { id: websiteId } } }))
  });
}

/** Rows per page of a website's crawl history and indexed content (apps/web's PAGINATION.PAGE_SIZE). */
export const WEBSITE_PAGE_SIZE = 100;

/** The website's latest run alone: cheap enough to poll for its state. */
export function websiteLatestRunQueryOptions(api: EneoClient, websiteId: string) {
  return queryOptions({
    queryKey: ["websites", websiteId, "crawl-runs", "latest"],
    queryFn: async (): Promise<CrawlRun | null> =>
      (await unwrap(
        api.GET("/api/v1/websites/{id}/runs/latest/", { params: { path: { id: websiteId } } })
      )) ?? null
  });
}

/** The website's crawl history, newest first, a page at a time. */
export function websiteCrawlRunsQueryOptions(api: EneoClient, websiteId: string) {
  return infiniteQueryOptions({
    ...cursorPagination,
    queryKey: ["websites", websiteId, "crawl-runs", "pages"],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/websites/{id}/runs/", {
          params: {
            path: { id: websiteId },
            query: { limit: WEBSITE_PAGE_SIZE, cursor: pageParam }
          }
        })
      )
  });
}

/** What the website has indexed, a page at a time. */
export function websiteBlobPagesQueryOptions(api: EneoClient, websiteId: string) {
  return infiniteQueryOptions({
    ...cursorPagination,
    queryKey: ["websites", websiteId, "info-blobs", "pages"],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/api/v1/websites/{id}/info-blobs/page/", {
          params: {
            path: { id: websiteId },
            query: { limit: WEBSITE_PAGE_SIZE, cursor: pageParam }
          }
        })
      )
  });
}

/** Failed addresses per page of the failures endpoint. */
export const CRAWL_FAILURES_PAGE_SIZE = 100;

/**
 * A run's recorded page and file failures (optionally one kind), oldest
 * first, a page at a time. The admin crawler page reads the same shape from
 * its own endpoint, so it passes its own options to the details dialog.
 */
export function crawlFailuresQueryOptions(
  api: EneoClient,
  runId: string,
  kind: CrawlFailure["kind"] | null
) {
  return infiniteQueryOptions({
    ...cursorPagination,
    queryKey: ["crawl-runs", runId, "failures", kind],
    queryFn: ({ pageParam }): Promise<CrawlFailurePage> =>
      unwrap(
        api.GET("/api/v1/crawl-runs/{id}/failures/", {
          params: {
            path: { id: runId },
            query: { limit: CRAWL_FAILURES_PAGE_SIZE, cursor: pageParam, kind }
          }
        })
      )
  });
}

export function websiteBlobsQueryOptions(api: EneoClient, websiteId: string) {
  return queryOptions({
    queryKey: ["websites", websiteId, "info-blobs"],
    queryFn: async (): Promise<InfoBlob[]> => {
      const page = await unwrap(
        api.GET("/api/v1/websites/{id}/info-blobs/", { params: { path: { id: websiteId } } })
      );
      return page.items;
    }
  });
}

/**
 * Embedding models referenced by a set of knowledge resources, deduplicated
 * and flagged with whether they are still enabled in the space. Used to group
 * list views per model and to warn about disabled models still in use.
 */
export function embeddingModelsInUse(
  resources: { embedding_model: EmbeddingModel }[],
  spaceModels: { id: string }[]
): (EmbeddingModel & { inSpace: boolean })[] {
  const spaceModelIds = new Set(spaceModels.map((model) => model.id));
  const seen = new Map<string, EmbeddingModel & { inSpace: boolean }>();
  for (const resource of resources) {
    const model = resource.embedding_model;
    if (!seen.has(model.id)) seen.set(model.id, { ...model, inSpace: spaceModelIds.has(model.id) });
  }
  return [...seen.values()];
}
