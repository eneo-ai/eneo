import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type ModelsPresentation = Schema<"ModelsPresentation">;
export type CompletionModelAdmin = Schema<"CompletionModelSecurityStatus">;
export type EmbeddingModelAdmin = Schema<"EmbeddingModelSecurityStatus">;
export type TranscriptionModelAdmin = Schema<"TranscriptionModelSecurityStatus">;
export type AdminModel = CompletionModelAdmin | EmbeddingModelAdmin | TranscriptionModelAdmin;

export type ModelKind = "completion" | "embedding" | "transcription";

export const MODELS_KEY = ["admin-models"];

export function adminModelsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: MODELS_KEY,
    queryFn: (): Promise<ModelsPresentation> => unwrap(api.GET("/api/v1/ai-models/"))
  });
}

export function modelLabel(model: { name: string; nickname?: string | null }): string {
  return model.nickname || model.name;
}

/** Group a model list by provider org, preserving first-seen order. */
export function groupByProvider<T extends { org?: string | null }>(
  models: T[]
): { provider: string; models: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const model of models) {
    const provider = model.org ?? "Other";
    const list = groups.get(provider) ?? [];
    list.push(model);
    groups.set(provider, list);
  }
  return [...groups.entries()].map(([provider, list]) => ({ provider, models: list }));
}
