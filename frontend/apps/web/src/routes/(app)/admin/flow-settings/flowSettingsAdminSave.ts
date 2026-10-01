import { EneoError } from "@eneo/eneo-js";
import type {
  AIBuilderBudgetSettingsUpdate,
  Eneo,
  FlowInputLimitsUpdate,
  FlowMappedExecutionPolicyUpdate,
  FlowRuntimePolicyUpdate,
  FlowRagEvidencePolicyUpdate
} from "@eneo/eneo-js";

type SettingsWriter = Pick<
  Eneo["settings"],
  | "updateFlowInputLimits"
  | "updateFlowRuntimePolicy"
  | "updateMappedExecutionPolicy"
  | "updateAIBuilderBudgetSettings"
  | "updateRagEvidencePolicy"
>;

export type FlowAdminSettingsUpdates = {
  inputLimits: FlowInputLimitsUpdate | null;
  runtimePolicy: FlowRuntimePolicyUpdate | null;
  mappedExecution: FlowMappedExecutionPolicyUpdate | null;
  builderBudget: AIBuilderBudgetSettingsUpdate | null;
  ragEvidence: FlowRagEvidencePolicyUpdate | null;
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
  const ragEvidence = updates.ragEvidence
    ? await settings.updateRagEvidencePolicy(updates.ragEvidence)
    : null;

  return {
    inputLimits,
    runtimePolicy,
    mappedExecution,
    builderBudget,
    ragEvidence
  };
}

const RUN_CAPACITY_EXCEEDED_CODE = "max_concurrent_runs_exceeds_server_capacity";

/** The server refused max concurrent flow runs because it is above server capacity. */
export function isRunCapacityExceededError(error: unknown): boolean {
  if (!(error instanceof EneoError)) return false;
  const response = error.response as { code?: unknown } | null | undefined;
  return response?.code === RUN_CAPACITY_EXCEEDED_CODE;
}
