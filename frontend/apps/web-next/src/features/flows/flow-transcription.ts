/**
 * The flow's transcription settings (`metadata_json.wizard`) as the core reads
 * them (`transcription_config.py`): the model that writes the text, the
 * language, the service that times the words and labels the speakers, whether
 * the speakers are labelled, and at most how many. Pure and unit-tested; the
 * reference editor's behaviour (`FlowSpeakerIdentification.svelte`,
 * `flowEditorMetadata.ts` in apps/web) is the spec.
 */
import { takesAudio } from "./editor/step-draft";
import type { FlowStep } from "./flows-api";

export const TRANSCRIPTION_LANGUAGES = ["sv", "en", "auto"] as const;
export type TranscriptionLanguage = (typeof TRANSCRIPTION_LANGUAGES)[number];

/** The language a run transcribes in when the flow names none. */
const DEFAULT_LANGUAGE: TranscriptionLanguage = "sv";

/**
 * The service choice: none made yet (the server fills in the organisation's
 * default on the next draft write), the author's "none" (text only, no word
 * timings), or one service.
 */
export type SpeakerServiceChoice =
  { kind: "unset" } | { kind: "none" } | { kind: "service"; id: string };

export type TranscriptionSettings = {
  enabled: boolean;
  modelId: string | null;
  language: TranscriptionLanguage;
  /** `transcription_diarization`: label who says what (on unless turned off). */
  speakerLabels: boolean;
  speakerService: SpeakerServiceChoice;
  /** The most speakers a run labels when it states no bound; null counts them. */
  maxSpeakers: number | null;
};

/** A transcription service granted to the space, as the space payload lists it. */
export type SpeakerServiceLink = {
  id: string;
  name: string;
  available: boolean;
  meets_security_classification: boolean;
  is_default: boolean;
};

type Metadata = Record<string, unknown> | null | undefined;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function wizardOf(metadata: Metadata): Record<string, unknown> {
  return isRecord(metadata?.wizard) ? metadata.wizard : {};
}

/** The id a `{ id }` reference names; a blank id reads as no choice, as the core reads it. */
function referenceId(reference: unknown): string | null {
  if (!isRecord(reference)) return null;
  const id = reference.id;
  return typeof id === "string" && id.trim() !== "" ? id : null;
}

export function transcriptionSettingsOf(metadata: Metadata): TranscriptionSettings {
  const wizard = wizardOf(metadata);
  const rawLanguage =
    typeof wizard.transcription_language === "string"
      ? wizard.transcription_language.trim().toLowerCase()
      : "";
  const service = wizard.transcription_speaker_service;
  const serviceId = referenceId(service);
  const max = wizard.transcription_max_speakers;
  return {
    enabled: wizard.transcription_enabled === true,
    modelId: referenceId(wizard.transcription_model),
    language: (TRANSCRIPTION_LANGUAGES as readonly string[]).includes(rawLanguage)
      ? (rawLanguage as TranscriptionLanguage)
      : DEFAULT_LANGUAGE,
    speakerLabels: wizard.transcription_diarization !== false,
    speakerService:
      serviceId !== null
        ? { kind: "service", id: serviceId }
        : "transcription_speaker_service" in wizard && service === null
          ? { kind: "none" }
          : { kind: "unset" },
    maxSpeakers: typeof max === "number" && Number.isInteger(max) && max >= 1 ? max : null
  };
}

/** Whether a step of the flow takes audio, which the core transcribes. */
export function flowTakesAudio(steps: readonly FlowStep[]): boolean {
  return steps.some((step) =>
    takesAudio({
      input_source: step.input_source,
      input_type: step.input_type,
      input_config: step.input_config ?? null
    })
  );
}

/** A step names the speakers, so every run labels them whatever the setting says. */
export function speakersRequired(steps: readonly Pick<FlowStep, "output_mode">[]): boolean {
  return steps.some((step) => step.output_mode === "speaker_mapping");
}

/** The granted services new work in the space may use (the core's rule). */
export function usableSpeakerServices<T extends SpeakerServiceLink>(services: readonly T[]): T[] {
  return services.filter((service) => service.meets_security_classification && service.available);
}

/** Why the chosen service cannot be used now, or null when it can (or none is chosen). */
export type LostServiceReason = "removed" | "disabled" | "classification";

export type SpeakerServiceState = {
  /** The chosen service, when the space may use it. */
  picked: SpeakerServiceLink | null;
  lost: { reason: LostServiceReason; name: string | null } | null;
  /** Whether speakers are labelled: a step needs them, or the author asked and chose a service. */
  labelled: boolean;
};

export function speakerServiceState(
  settings: Pick<TranscriptionSettings, "speakerService" | "speakerLabels">,
  services: readonly SpeakerServiceLink[],
  required: boolean
): SpeakerServiceState {
  const choice = settings.speakerService;
  const pickedId = choice.kind === "service" ? choice.id : null;
  const picked = usableSpeakerServices(services).find((service) => service.id === pickedId) ?? null;
  let lost: SpeakerServiceState["lost"] = null;
  if (pickedId !== null && picked === null) {
    const link = services.find((service) => service.id === pickedId);
    lost = !link
      ? { reason: "removed", name: null }
      : {
          reason: link.meets_security_classification ? "disabled" : "classification",
          name: link.name
        };
  }
  return {
    picked,
    lost,
    labelled: required || (settings.speakerLabels && choice.kind !== "none")
  };
}

/** Choosing a service, or none: none is text only, so it labels no speakers either. */
export function withSpeakerService(
  settings: TranscriptionSettings,
  serviceId: string | null
): TranscriptionSettings {
  return serviceId === null
    ? { ...settings, speakerService: { kind: "none" }, speakerLabels: false }
    : { ...settings, speakerService: { kind: "service", id: serviceId } };
}

/** The bound typed for the speakers: empty counts them, else a whole number of at least 1. */
export function parseMaxSpeakers(value: number | null | undefined): number | null | undefined {
  if (value === null || value === undefined) return null;
  return Number.isInteger(value) && value >= 1 ? value : undefined;
}

/**
 * The flow's metadata with the transcription settings that changed from
 * `saved` to `draft`; the wizard's other keys, and the settings that did not
 * change, stay exactly as stored. A flow that takes audio is always
 * transcribed (the core refuses it otherwise).
 */
export function metadataWithTranscription(
  metadata: Metadata,
  saved: TranscriptionSettings,
  draft: TranscriptionSettings,
  options: { takesAudio: boolean }
): Record<string, unknown> {
  const wizard: Record<string, unknown> = { ...wizardOf(metadata) };
  const before = { ...wizard };
  const enabled = draft.enabled || options.takesAudio;
  if (enabled !== saved.enabled) wizard.transcription_enabled = enabled;
  if (draft.modelId !== saved.modelId) {
    wizard.transcription_model = draft.modelId === null ? null : { id: draft.modelId };
  }
  if (draft.language !== saved.language) wizard.transcription_language = draft.language;
  if (draft.speakerLabels !== saved.speakerLabels) {
    wizard.transcription_diarization = draft.speakerLabels;
  }
  if (JSON.stringify(draft.speakerService) !== JSON.stringify(saved.speakerService)) {
    if (draft.speakerService.kind === "unset") delete wizard.transcription_speaker_service;
    else if (draft.speakerService.kind === "none") wizard.transcription_speaker_service = null;
    else wizard.transcription_speaker_service = { id: draft.speakerService.id };
  }
  if (draft.maxSpeakers !== saved.maxSpeakers) {
    if (draft.maxSpeakers === null) delete wizard.transcription_max_speakers;
    else wizard.transcription_max_speakers = draft.maxSpeakers;
  }
  const next: Record<string, unknown> = { ...(metadata ?? {}) };
  if (JSON.stringify(wizard) !== JSON.stringify(before)) next.wizard = wizard;
  return next;
}

/**
 * A draft that transcribes audio and has no model chosen: the core saves it
 * and refuses to publish it. Nothing chooses a model for the flow.
 */
export function transcriptionModelMissing(
  settings: Pick<TranscriptionSettings, "modelId">,
  steps: readonly FlowStep[]
): boolean {
  return flowTakesAudio(steps) && settings.modelId === null;
}
