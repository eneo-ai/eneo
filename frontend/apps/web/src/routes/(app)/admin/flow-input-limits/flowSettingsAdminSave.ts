import type {
  AIBuilderBudgetSettingsUpdate,
  Eneo,
  FlowInputLimitsUpdate,
  FlowMappedExecutionPolicyUpdate,
  FlowRuntimePolicyUpdate
} from "@eneo/eneo-js";

type SettingsWriter = Pick<
  Eneo["settings"],
  | "updateFlowInputLimits"
  | "updateFlowRuntimePolicy"
  | "updateMappedExecutionPolicy"
  | "updateAIBuilderBudgetSettings"
>;

export type FlowAdminSettingsUpdates = {
  inputLimits: FlowInputLimitsUpdate | null;
  runtimePolicy: FlowRuntimePolicyUpdate | null;
  mappedExecution: FlowMappedExecutionPolicyUpdate | null;
  builderBudget: AIBuilderBudgetSettingsUpdate | null;
};

/**
 * Serialize writes because every endpoint replaces the shared flow-settings snapshot.
 */
export async function saveFlowAdminSettings(
  settings: SettingsWriter,
  updates: FlowAdminSettingsUpdates
) {
  const inputLimits = updates.inputLimits
    ? await settings.updateFlowInputLimits(updates.inputLimits)
    : null;
  const runtimePolicy = updates.runtimePolicy
    ? await settings.updateFlowRuntimePolicy(updates.runtimePolicy)
    : null;
  const mappedExecution = updates.mappedExecution
    ? await settings.updateMappedExecutionPolicy(updates.mappedExecution)
    : null;
  const builderBudget = updates.builderBudget
    ? await settings.updateAIBuilderBudgetSettings(updates.builderBudget)
    : null;

  return {
    inputLimits,
    runtimePolicy,
    mappedExecution,
    builderBudget
  };
}
