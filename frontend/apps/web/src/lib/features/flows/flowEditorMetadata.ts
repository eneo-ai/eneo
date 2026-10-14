import type { Flow } from "@eneo/eneo-js";
import { stepsTakeAudio } from "./flowRuntimeInputConfig";

export type FlowWizardMetadata = {
  transcription_enabled?: boolean;
  transcription_model?: { id: string } | null;
  transcription_language?: string;
  transcription_diarization?: boolean;
  // The service that times the words and, with transcription_diarization,
  // labels the speakers. Null is the author's "none" (text only); absent is
  // no choice yet, which the server fills with the organisation's default.
  transcription_speaker_service?: { id: string } | null;
  // The most speakers a run labels when it states no bound; absent = automatic.
  transcription_max_speakers?: number | null;
};

type SpeakerServiceLink = { meets_security_classification: boolean; available: boolean };

/** The granted services new work in the space may use (the backend's rule). */
export function usableSpeakerServices<T extends SpeakerServiceLink>(services: T[]): T[] {
  return services.filter((service) => service.meets_security_classification && service.available);
}

/**
 * The id a `{ id }` reference in the wizard metadata names. A blank id reads
 * as no choice, as the backend reads it (parse_transcription_config).
 */
export function wizardReferenceId(reference: { id?: unknown } | null | undefined): string | null {
  const id = reference?.id;
  return typeof id === "string" && id.trim() !== "" ? id : null;
}

/**
 * A draft that transcribes audio and whose author has chosen no transcription
 * model. The server saves such a draft and refuses to publish it; nothing is
 * chosen for the flow.
 */
export function transcriptionModelNotChosen(args: {
  wizard: FlowWizardMetadata;
  transcriptionEnabled: boolean;
  steps: Parameters<typeof stepsTakeAudio>[0];
}): boolean {
  return (
    args.transcriptionEnabled &&
    wizardReferenceId(args.wizard.transcription_model) === null &&
    stepsTakeAudio(args.steps)
  );
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
