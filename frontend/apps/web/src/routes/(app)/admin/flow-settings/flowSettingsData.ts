import type { PageData } from "./$types";

type Loaded<T> = Exclude<T, null>;

/** The page data once the admin-only settings are present (the user has admin). */
export type FlowSettingsAdminData = PageData & {
  flowRetentionPolicy: Loaded<PageData["flowRetentionPolicy"]>;
  flowInputLimits: Loaded<PageData["flowInputLimits"]>;
  flowRuntimePolicy: Loaded<PageData["flowRuntimePolicy"]>;
  mappedExecutionPolicy: Loaded<PageData["mappedExecutionPolicy"]>;
  aiBuilderBudgetSettings: Loaded<PageData["aiBuilderBudgetSettings"]>;
  ragEvidencePolicy: Loaded<PageData["ragEvidencePolicy"]>;
};

export function adminSettingsData(data: PageData): FlowSettingsAdminData | null {
  if (
    !data.access.admin ||
    data.flowRetentionPolicy === null ||
    data.flowInputLimits === null ||
    data.flowRuntimePolicy === null ||
    data.mappedExecutionPolicy === null ||
    data.aiBuilderBudgetSettings === null ||
    data.ragEvidencePolicy === null
  ) {
    return null;
  }
  return data as FlowSettingsAdminData;
}
