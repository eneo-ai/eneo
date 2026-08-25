import type { FlowStep } from "@eneo/eneo-js";
import type { FlowFormField } from "./flowFormSchema";

/** Form field types whose value can be read as a list of participant names. */
export const SPEAKER_MAPPING_PARTICIPANT_FIELD_TYPES = new Set(["text", "multiselect"]);

export function getSpeakerMappingParticipantsField(
  step: Pick<FlowStep, "output_config">
): string | null {
  const config = step.output_config;
  if (!config || typeof config !== "object" || Array.isArray(config)) return null;
  const block = (config as Record<string, unknown>).speaker_mapping;
  if (!block || typeof block !== "object" || Array.isArray(block)) return null;
  const value = (block as Record<string, unknown>).participants_field;
  return typeof value === "string" && value.trim() ? value : null;
}

/** Form field types usable as an expected speaker count. */
export const SPEAKER_MAPPING_SPEAKER_COUNT_FIELD_TYPES = new Set(["number"]);

function configField(step: Pick<FlowStep, "output_config">, key: string): string | null {
  const config = step.output_config;
  if (!config || typeof config !== "object" || Array.isArray(config)) return null;
  const block = (config as Record<string, unknown>).speaker_mapping;
  if (!block || typeof block !== "object" || Array.isArray(block)) return null;
  const value = (block as Record<string, unknown>)[key];
  return typeof value === "string" && value.trim() ? value : null;
}

export function getSpeakerMappingSpeakerCountField(
  step: Pick<FlowStep, "output_config">
): string | null {
  return configField(step, "speaker_count_field");
}

export function buildSpeakerMappingOutputConfig(
  outputConfig: FlowStep["output_config"],
  participantsField: string | null,
  speakerCountField: string | null = getSpeakerMappingSpeakerCountField({
    output_config: outputConfig
  })
): Record<string, unknown> {
  const base =
    outputConfig && typeof outputConfig === "object" && !Array.isArray(outputConfig)
      ? (outputConfig as Record<string, unknown>)
      : {};
  return {
    ...base,
    speaker_mapping: {
      participants_field: participantsField,
      speaker_count_field: speakerCountField
    }
  };
}

export function getSpeakerCountFieldOptions(
  fields: Pick<FlowFormField, "name" | "type" | "label">[] | undefined
): Pick<FlowFormField, "name" | "type" | "label">[] {
  return (fields ?? []).filter((field) =>
    SPEAKER_MAPPING_SPEAKER_COUNT_FIELD_TYPES.has(String(field.type))
  );
}

export function getParticipantFieldOptions(
  fields: Pick<FlowFormField, "name" | "type" | "label">[] | undefined
): Pick<FlowFormField, "name" | "type" | "label">[] {
  return (fields ?? []).filter((field) =>
    SPEAKER_MAPPING_PARTICIPANT_FIELD_TYPES.has(String(field.type))
  );
}
