import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type ModelsPresentation = Schema<"ModelsPresentation">;
export type CompletionModelAdmin = Schema<"CompletionModelSecurityStatus">;
export type EmbeddingModelAdmin = Schema<"EmbeddingModelSecurityStatus">;
export type TranscriptionModelAdmin = Schema<"TranscriptionModelSecurityStatus">;
export type AdminModel = CompletionModelAdmin | EmbeddingModelAdmin | TranscriptionModelAdmin;
export type TenantCompletionModelCreate = Schema<"TenantCompletionModelCreate">;
export type TenantCompletionModelUpdate = Schema<"TenantCompletionModelUpdate">;
export type TenantEmbeddingModelCreate = Schema<"TenantEmbeddingModelCreate">;
export type TenantEmbeddingModelUpdate = Schema<"TenantEmbeddingModelUpdate">;
export type TenantTranscriptionModelCreate = Schema<"TenantTranscriptionModelCreate">;
export type TenantTranscriptionModelUpdate = Schema<"TenantTranscriptionModelUpdate">;
export type ModelUsageStatistics = Schema<"ModelUsageStatistics">;
export type TranscriptionModelUsageStats = Schema<"TranscriptionModelUsageStats">;
export type ValidationResult = Schema<"ValidationResult">;
export type ModelMigrationHistory = Schema<"ModelMigrationHistory"> & {
  model_type: "completion" | "transcription";
};

export type ModelKind = "completion" | "embedding" | "transcription";
export type MigratableModelKind = "completion" | "transcription";

export const MODELS_KEY = ["admin-models"];
export const MODEL_MIGRATION_HISTORY_KEY = ["model-migration-history"];

/** Merged completion + transcription migration history, newest first. */
export function migrationHistoryQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: MODEL_MIGRATION_HISTORY_KEY,
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

/** Usage impact of a migratable model (assistants/apps/etc. that reference it). */
export function modelUsageQueryOptions(
  api: EneoClient,
  modelId: string,
  kind: MigratableModelKind
) {
  return queryOptions({
    queryKey: ["model-usage", kind, modelId],
    queryFn: async (): Promise<ModelUsageStatistics> => {
      if (kind === "transcription") {
        const data = await unwrap(
          api.GET("/api/v1/transcription-models/{model_id}/usage", {
            params: { path: { model_id: modelId } }
          })
        );
        return {
          model_id: data.model_id,
          total_usage: data.total_count ?? (data.apps_count ?? 0) + (data.spaces_count ?? 0),
          assistants_count: 0,
          apps_count: data.apps_count ?? 0,
          services_count: 0,
          spaces_count: data.spaces_count ?? 0,
          questions_count: 0,
          assistant_templates_count: 0,
          app_templates_count: 0,
          last_updated: new Date(0).toISOString()
        };
      }
      return unwrap(
        api.GET("/api/v1/completion-models/{model_id}/usage", {
          params: { path: { model_id: modelId } }
        })
      );
    }
  });
}

export type ModelUsageEntity = {
  entity_id: string;
  entity_name: string;
  entity_type: string;
  space_name?: string | null;
  owner_name?: string | null;
};

/** Per-model usage details: which assistants/apps/services reference a model. */
export function modelUsageDetailsQueryOptions(
  api: EneoClient,
  modelId: string,
  kind: "completion" | "transcription"
) {
  return queryOptions({
    queryKey: ["model-usage-details", kind, modelId],
    queryFn: async (): Promise<{ items: ModelUsageEntity[]; total: number }> => {
      const res =
        kind === "transcription"
          ? await unwrap(
              api.GET("/api/v1/transcription-models/{model_id}/usage/details", {
                params: { path: { model_id: modelId } }
              })
            )
          : await unwrap(
              api.GET("/api/v1/completion-models/{model_id}/usage/details", {
                params: { path: { model_id: modelId } }
              })
            );
      const items = (res.items ?? []).map((item) => ({
        entity_id: item.entity_id,
        entity_name: item.entity_name,
        entity_type: item.entity_type ?? "app",
        space_name: item.space_name ?? null,
        owner_name: item.owner_name ?? null
      }));
      return { items, total: res.total ?? items.length };
    }
  });
}

/** Compatibility check for migrating one completion model's usage to another. */
export function validateMigrationQueryOptions(
  api: EneoClient,
  modelId: string,
  toModelId: string,
  kind: MigratableModelKind
) {
  return queryOptions({
    queryKey: ["model-migration-validate", kind, modelId, toModelId],
    queryFn: (): Promise<ValidationResult> => {
      if (kind === "transcription") {
        return unwrap(
          api.GET("/api/v1/transcription-models/{model_id}/migration-validate", {
            params: { path: { model_id: modelId }, query: { to_model_id: toModelId } }
          })
        );
      }
      return unwrap(
        api.GET("/api/v1/completion-models/{model_id}/migration-validate", {
          params: { path: { model_id: modelId }, query: { to_model_id: toModelId } }
        })
      );
    }
  });
}

export function migrateModelUsage(
  api: EneoClient,
  kind: MigratableModelKind,
  modelId: string,
  toModelId: string,
  forceOverride: boolean
) {
  const body = { to_model_id: toModelId, confirm_migration: true, force_override: forceOverride };
  if (kind === "transcription") {
    return unwrap(
      api.POST("/api/v1/transcription-models/{model_id}/migrate", {
        params: { path: { model_id: modelId } },
        body
      })
    );
  }
  return unwrap(
    api.POST("/api/v1/completion-models/{model_id}/migrate", {
      params: { path: { model_id: modelId } },
      body
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

export function createTenantModel(
  api: EneoClient,
  kind: "completion",
  body: TenantCompletionModelCreate
): Promise<unknown>;
export function createTenantModel(
  api: EneoClient,
  kind: "embedding",
  body: TenantEmbeddingModelCreate
): Promise<unknown>;
export function createTenantModel(
  api: EneoClient,
  kind: "transcription",
  body: TenantTranscriptionModelCreate
): Promise<unknown>;
export function createTenantModel(
  api: EneoClient,
  kind: ModelKind,
  body: TenantCompletionModelCreate | TenantEmbeddingModelCreate | TenantTranscriptionModelCreate
) {
  if (kind === "embedding") {
    return unwrap(
      api.POST("/api/v1/admin/tenant-models/embedding/", {
        body: body as TenantEmbeddingModelCreate
      })
    );
  }
  if (kind === "transcription") {
    return unwrap(
      api.POST("/api/v1/admin/tenant-models/transcription/", {
        body: body as TenantTranscriptionModelCreate
      })
    );
  }
  return unwrap(
    api.POST("/api/v1/admin/tenant-models/completion/", {
      body: body as TenantCompletionModelCreate
    })
  );
}

export function updateTenantModel(
  api: EneoClient,
  kind: "completion",
  modelId: string,
  body: TenantCompletionModelUpdate
): Promise<unknown>;
export function updateTenantModel(
  api: EneoClient,
  kind: "embedding",
  modelId: string,
  body: TenantEmbeddingModelUpdate
): Promise<unknown>;
export function updateTenantModel(
  api: EneoClient,
  kind: "transcription",
  modelId: string,
  body: TenantTranscriptionModelUpdate
): Promise<unknown>;
export function updateTenantModel(
  api: EneoClient,
  kind: ModelKind,
  modelId: string,
  body: TenantCompletionModelUpdate | TenantEmbeddingModelUpdate | TenantTranscriptionModelUpdate
) {
  if (kind === "embedding") {
    return unwrap(
      api.PUT("/api/v1/admin/tenant-models/embedding/{model_id}/", {
        params: { path: { model_id: modelId } },
        body: body as TenantEmbeddingModelUpdate
      })
    );
  }
  if (kind === "transcription") {
    return unwrap(
      api.PUT("/api/v1/admin/tenant-models/transcription/{model_id}/", {
        params: { path: { model_id: modelId } },
        body: body as TenantTranscriptionModelUpdate
      })
    );
  }
  return updateCompletionModel(api, modelId, body as TenantCompletionModelUpdate);
}

export function deleteTenantModel(api: EneoClient, kind: ModelKind, modelId: string) {
  if (kind === "embedding") {
    return unwrap(
      api.DELETE("/api/v1/admin/tenant-models/embedding/{model_id}/", {
        params: { path: { model_id: modelId } }
      })
    );
  }
  if (kind === "transcription") {
    return unwrap(
      api.DELETE("/api/v1/admin/tenant-models/transcription/{model_id}/", {
        params: { path: { model_id: modelId } }
      })
    );
  }
  return unwrap(
    api.DELETE("/api/v1/admin/tenant-models/completion/{model_id}/", {
      params: { path: { model_id: modelId } }
    })
  );
}

export function validateProviderModel(
  api: EneoClient,
  providerId: string,
  body: { model_name: string; model_type: ModelKind }
) {
  return unwrap(
    api.POST("/api/v1/admin/model-providers/{provider_id}/validate-model/", {
      params: { path: { provider_id: providerId } },
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

export function isMigrationSecurityBlockerCode(code: string | undefined): boolean {
  return code?.startsWith("security_classification_insufficient") ?? false;
}

type Translate = (key: string, values?: Record<string, number | string>) => string;

export function migrationWarningLabel(t: Translate, warning: string, code?: string): string {
  if (!code) return warning;
  const [kind, first, second] = code.split(":");
  switch (kind) {
    case "target_deprecated":
      return t("migration_warning_target_deprecated");
    case "lower_token_limit":
      return t("migration_warning_lower_token_limit", { limit: first ?? "" });
    case "different_family":
      return t("migration_warning_different_family", { from: first ?? "", to: second ?? "" });
    case "lacks_vision":
      return t("migration_warning_lacks_vision");
    case "lacks_reasoning":
      return t("migration_warning_lacks_reasoning");
    case "lacks_tool_calling":
      return t("migration_warning_lacks_tool_calling");
    case "kwargs_reset":
      return t("migration_warning_kwargs_reset");
    case "security_classification_insufficient":
      return t("migration_warning_security_classification_insufficient", {
        count: Number(first ?? 0),
        classification: second ?? t("none")
      });
    default:
      return warning;
  }
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
