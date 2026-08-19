import type {
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
  | "updateRagEvidencePolicy"
>;

export type FlowAdminSettingsUpdates = {
  inputLimits: FlowInputLimitsUpdate | null;
  runtimePolicy: FlowRuntimePolicyUpdate | null;
  mappedExecution: FlowMappedExecutionPolicyUpdate | null;
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
  const ragEvidence = updates.ragEvidence
    ? await settings.updateRagEvidencePolicy(updates.ragEvidence)
    : null;

  return {
    inputLimits,
    runtimePolicy,
    mappedExecution,
    ragEvidence
  };
}
