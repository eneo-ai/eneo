import type { Flow } from "@eneo/eneo-js";

export type FlowWizardMetadata = {
  transcription_enabled?: boolean;
  transcription_model?: { id: string } | null;
  transcription_language?: string;
};

export type FlowSaveStatus = "saved" | "saving" | "unsaved";

export function getFlowWizardMetadata(
  metadata: Flow["metadata_json"] | null | undefined
): FlowWizardMetadata {
  const wizard = metadata?.wizard;
  if (typeof wizard === "object" && wizard !== null && !Array.isArray(wizard)) {
    return wizard as FlowWizardMetadata;
  }
  return {};
}

/**
 * Collapse the flow-level and assistant-level save states into a single status:
 * any in-flight save shows "saving"; a pending or errored assistant save keeps
 * the flow "unsaved"; otherwise mirror the flow status.
 */
export function getUnifiedFlowSaveStatus(
  flowStatus: FlowSaveStatus,
  assistantStatus: "idle" | "pending" | "saving" | "error"
): FlowSaveStatus {
  if (assistantStatus === "saving" || flowStatus === "saving") return "saving";
  if (assistantStatus === "error" || assistantStatus === "pending") return "unsaved";
  if (flowStatus === "unsaved") return "unsaved";
  return "saved";
}
