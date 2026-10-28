import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type AssistantTemplate = Schema<"AssistantTemplateAdminPublic">;
export type AppTemplate = Schema<"AppTemplateAdminPublic">;
export type AssistantTemplateCreate = Schema<"AssistantTemplateAdminCreate">;
export type AssistantTemplateUpdate = Schema<"AssistantTemplateAdminUpdate">;
export type AppTemplateCreate = Schema<"AppTemplateAdminCreate">;
export type AppTemplateUpdate = Schema<"AppTemplateAdminUpdate">;

export const ASSISTANT_KEY = ["admin-templates", "assistants"];
export const APP_KEY = ["admin-templates", "apps"];
export const DELETED_ASSISTANT_KEY = ["admin-templates", "assistants", "deleted"];
export const DELETED_APP_KEY = ["admin-templates", "apps", "deleted"];

export function assistantTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ASSISTANT_KEY,
    queryFn: async (): Promise<AssistantTemplate[]> => {
      const page = await unwrap(api.GET("/api/v1/admin/templates/assistants/"));
      return page.items.filter((item) => !item.deleted_at);
    }
  });
}
export function appTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: APP_KEY,
    queryFn: async (): Promise<AppTemplate[]> => {
      const page = await unwrap(api.GET("/api/v1/admin/templates/apps/"));
      return page.items.filter((item) => !item.deleted_at);
    }
  });
}

export function deletedAssistantTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: DELETED_ASSISTANT_KEY,
    queryFn: async (): Promise<AssistantTemplate[]> =>
      (await unwrap(api.GET("/api/v1/admin/templates/assistants/deleted"))).items
  });
}
export function deletedAppTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: DELETED_APP_KEY,
    queryFn: async (): Promise<AppTemplate[]> =>
      (await unwrap(api.GET("/api/v1/admin/templates/apps/deleted"))).items
  });
}

export function createAssistantTemplate(api: EneoClient, body: AssistantTemplateCreate) {
  return unwrap(api.POST("/api/v1/admin/templates/assistants/", { body }));
}
export function updateAssistantTemplate(
  api: EneoClient,
  templateId: string,
  body: AssistantTemplateUpdate
) {
  return unwrap(
    api.PATCH("/api/v1/admin/templates/assistants/{template_id}", {
      params: { path: { template_id: templateId } },
      body
    })
  );
}
export function createAppTemplate(api: EneoClient, body: AppTemplateCreate) {
  return unwrap(api.POST("/api/v1/admin/templates/apps/", { body }));
}
export function updateAppTemplate(api: EneoClient, templateId: string, body: AppTemplateUpdate) {
  return unwrap(
    api.PATCH("/api/v1/admin/templates/apps/{template_id}", {
      params: { path: { template_id: templateId } },
      body
    })
  );
}

export function rollbackAssistantTemplate(api: EneoClient, templateId: string) {
  return unwrap(
    api.POST("/api/v1/admin/templates/assistants/{template_id}/rollback", {
      params: { path: { template_id: templateId } }
    })
  );
}

export function rollbackAppTemplate(api: EneoClient, templateId: string) {
  return unwrap(
    api.POST("/api/v1/admin/templates/apps/{template_id}/rollback", {
      params: { path: { template_id: templateId } }
    })
  );
}

export type TemplateKind = "assistants" | "apps";

type CategoryTitleKey =
  | "template_category_communication"
  | "template_category_qa"
  | "template_category_advice"
  | "template_category_misc"
  | "template_category_transcription";

type CategoryDescriptionKey =
  | "template_category_communication_description"
  | "template_category_qa_description"
  | "template_category_advice_description"
  | "template_category_misc_assistants_description"
  | "template_category_transcription_description"
  | "template_category_misc_apps_description";

export type TemplateCategory = {
  /** What is stored: an English slug. */
  value: string;
  title: CategoryTitleKey;
  description: CategoryDescriptionKey;
};

/**
 * The predefined categories per template kind (the Svelte app's
 * TemplateCategories), in the order the editor offers them; the first is a
 * new template's category. Admins can also type their own.
 */
export const TEMPLATE_CATEGORIES: Record<TemplateKind, readonly TemplateCategory[]> = {
  assistants: [
    {
      value: "communication",
      title: "template_category_communication",
      description: "template_category_communication_description"
    },
    {
      value: "q&a",
      title: "template_category_qa",
      description: "template_category_qa_description"
    },
    {
      value: "advice",
      title: "template_category_advice",
      description: "template_category_advice_description"
    },
    {
      value: "misc",
      title: "template_category_misc",
      description: "template_category_misc_assistants_description"
    }
  ],
  apps: [
    {
      value: "transcription",
      title: "template_category_transcription",
      description: "template_category_transcription_description"
    },
    {
      value: "misc",
      title: "template_category_misc",
      description: "template_category_misc_apps_description"
    }
  ]
};

/** The predefined category stored as `value` for this kind, if it is one. */
export function predefinedCategory(
  kind: TemplateKind,
  value: string
): TemplateCategory | undefined {
  return TEMPLATE_CATEGORIES[kind].find((category) => category.value === value);
}

/** A custom slug as a title: `customer-service` → `Customer Service`. */
function formatCategoryTitle(category: string): string {
  return category
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

/**
 * What a list shows for a stored category: a predefined one's translated
 * title and description (matched case-insensitively), or a custom slug as a
 * title without a description.
 */
export function templateCategoryInfo(
  kind: TemplateKind,
  category: string,
  t: (key: CategoryTitleKey | CategoryDescriptionKey) => string
): { title: string; description: string | null } {
  const predefined = predefinedCategory(kind, category.trim().toLowerCase());
  if (predefined) return { title: t(predefined.title), description: t(predefined.description) };
  const other = TEMPLATE_CATEGORIES.assistants
    .concat(TEMPLATE_CATEGORIES.apps)
    .find((candidate) => candidate.value === category.trim().toLowerCase());
  return { title: other ? t(other.title) : formatCategoryTitle(category), description: null };
}

/**
 * The completion model a template form starts with: the template's own (by
 * id, or by name for a model since replaced), else the first available.
 */
export function findTemplateModel<T extends { id: string; name: string }>(
  models: readonly T[],
  template?: { completion_model_id?: string | null; completion_model_name?: string | null }
): T | null {
  const match =
    template &&
    models.find(
      (model) =>
        model.id === template.completion_model_id || model.name === template.completion_model_name
    );
  return match || models[0] || null;
}
