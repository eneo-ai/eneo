import type { Flow } from "@eneo/eneo-js";

export type FlowWizardMetadata = {
  transcription_enabled?: boolean;
  transcription_model?: { id: string } | null;
  transcription_language?: string;
  transcription_diarization?: boolean;
  // The speaker identification service the author picked; absent means the
  // space's only usable one.
  transcription_speaker_service?: { id: string } | null;
  // The most speakers a run labels when it states no bound; absent = automatic.
  transcription_max_speakers?: number | null;
};

type SpeakerServiceLink = { meets_security_classification: boolean; available: boolean };

/** The granted services new work in the space may use (the backend's rule). */
export function usableSpeakerServices<T extends SpeakerServiceLink>(services: T[]): T[] {
  return services.filter((service) => service.meets_security_classification && service.available);
}

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
