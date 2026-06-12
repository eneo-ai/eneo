import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type Collection = Schema<"CollectionPublic">;
export type Website = Schema<"WebsitePublic">;
export type CrawlRun = NonNullable<Website["latest_crawl"]>;
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

export function websiteCrawlRunsQueryOptions(api: EneoClient, websiteId: string) {
  return queryOptions({
    queryKey: ["websites", websiteId, "crawl-runs"],
    queryFn: async (): Promise<CrawlRun[]> => {
      const page = await unwrap(
        api.GET("/api/v1/websites/{id}/runs/", { params: { path: { id: websiteId } } })
      );
      // Newest first; the backend returns runs in creation order.
      return [...page.items].reverse();
    }
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
