import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type ModelsPresentation = Schema<"ModelsPresentation">;
export type CompletionModelAdmin = Schema<"CompletionModelSecurityStatus">;
export type EmbeddingModelAdmin = Schema<"EmbeddingModelSecurityStatus">;
export type TranscriptionModelAdmin = Schema<"TranscriptionModelSecurityStatus">;
export type AdminModel = CompletionModelAdmin | EmbeddingModelAdmin | TranscriptionModelAdmin;
export type TenantCompletionModelUpdate = Schema<"TenantCompletionModelUpdate">;
export type ModelUsageStatistics = Schema<"ModelUsageStatistics">;
export type ValidationResult = Schema<"ValidationResult">;
export type ModelMigrationHistory = Schema<"ModelMigrationHistory"> & {
  model_type: "completion" | "transcription";
};

export type ModelKind = "completion" | "embedding" | "transcription";

export const MODELS_KEY = ["admin-models"];

/** Merged completion + transcription migration history, newest first. */
export function migrationHistoryQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["model-migration-history"],
    queryFn: async (): Promise<ModelMigrationHistory[]> => {
      const [completion, transcription] = await Promise.all([
        unwrap(api.GET("/api/v1/completion-models/migration-history")),
        unwrap(api.GET("/api/v1/transcription-models/migration-history"))
      ]);
      const tagged: ModelMigrationHistory[] = [
        ...completion.map((h) => ({ ...h, model_type: "completion" as const })),
        ...transcription.map((h) => ({ ...h, model_type: "transcription" as const }))
      ];
      return tagged.sort((a, b) =>
        (b.completed_at ?? b.started_at ?? "").localeCompare(a.completed_at ?? a.started_at ?? "")
      );
    }
  });
}

/** Usage impact of a completion model (assistants/apps/etc. that reference it). */
export function modelUsageQueryOptions(api: EneoClient, modelId: string) {
  return queryOptions({
    queryKey: ["model-usage", modelId],
    queryFn: (): Promise<ModelUsageStatistics> =>
      unwrap(
        api.GET("/api/v1/completion-models/{model_id}/usage", {
          params: { path: { model_id: modelId } }
        })
      )
  });
}

/** Compatibility check for migrating one completion model's usage to another. */
export function validateMigrationQueryOptions(api: EneoClient, modelId: string, toModelId: string) {
  return queryOptions({
    queryKey: ["model-migration-validate", modelId, toModelId],
    queryFn: (): Promise<ValidationResult> =>
      unwrap(
        api.GET("/api/v1/completion-models/{model_id}/migration-validate", {
          params: { path: { model_id: modelId }, query: { to_model_id: toModelId } }
        })
      )
  });
}

export function migrateModelUsage(api: EneoClient, modelId: string, toModelId: string) {
  return unwrap(
    api.POST("/api/v1/completion-models/{model_id}/migrate", {
      params: { path: { model_id: modelId } },
      body: { to_model_id: toModelId, confirm_migration: true }
    })
  );
}

/** Edit a tenant (custom) completion model's metadata/costs/capabilities. */
export function updateCompletionModel(
  api: EneoClient,
  modelId: string,
  body: TenantCompletionModelUpdate
) {
  return unwrap(
    api.PUT("/api/v1/admin/tenant-models/completion/{model_id}/", {
      params: { path: { model_id: modelId } },
      body
    })
  );
}

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
