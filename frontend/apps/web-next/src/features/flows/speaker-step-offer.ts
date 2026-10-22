/**
 * The shortcut that offers a step naming the speakers after the step that
 * transcribes, as the reference editor offered it (`insertSpeakerMappingStepAfter`
 * in apps/web `FlowEditor.ts`): when the flow labels speakers with a service
 * the space may use and no step names them yet. Whether the step may stand
 * there, and the configuration it starts with, are the core's answer for the
 * place after the transcribing step (`GET /flows/{id}/step-kinds/`). The new
 * step reads the transcript, a person reviews and corrects it, and it takes
 * the participants from the run form, which gets a list field for them when
 * it has no field that fits. Pure and unit-tested.
 */
import {
  newStepUpdate,
  uniqueStepName,
  type StepKindOption,
  type StepKindPlace
} from "./editor/step-kinds";
import { withSpeakerMapping } from "./editor/step-configs";
import type { EditorUpdate } from "./editor/step-types";
import type { FlowPublic, FlowStep } from "./flows-api";
import {
  evidenceExportAllowed,
  formFieldsOf,
  metadataWithSettings,
  suggestedFieldName,
  type FormFieldDraft
} from "./flow-form-fields";
import { stepsInOrder } from "./flow-steps";
import {
  speakerServiceState,
  speakersRequired,
  transcriptionSettingsOf,
  type SpeakerServiceLink
} from "./flow-transcription";

/**
 * The audio step the shortcut would follow, or null when nothing is offered;
 * the core's answer for the place after it decides (`speakerStepOption`).
 */
export function speakerStepCandidate(
  flow: Pick<FlowPublic, "steps" | "metadata_json">,
  services: readonly SpeakerServiceLink[]
): FlowStep | null {
  const steps = stepsInOrder(flow);
  if (speakersRequired(steps)) return null;
  const settings = transcriptionSettingsOf(flow.metadata_json);
  if (!settings.enabled || !settings.speakerLabels) return null;
  if (speakerServiceState(settings, services, false).picked === null) return null;
  return steps.find((step) => step.input_type === "audio") ?? null;
}

/** The speaker step the core allows at the place after the candidate, or null. */
export function speakerStepOption(place: StepKindPlace | undefined): StepKindOption | null {
  return place?.options.find((option) => option.kind === "speakers" && option.allowed) ?? null;
}

/** The run form field the participants come from: a list, else a multiselect or text field. */
function participantsFieldOf(fields: readonly FormFieldDraft[]): FormFieldDraft | null {
  return (
    fields.find((field) => field.type === "list") ??
    fields.find((field) => field.type === "multiselect" || field.type === "text") ??
    null
  );
}

/**
 * The editor update that adds the speaker step after `after` (named
 * `names.step`) with the configuration the core gives it there (`option`),
 * and, when the run form has no field for the participants, the list field
 * it reads them from (`names.fieldLabel`, with a technical name made from
 * `names.fieldName`).
 */
export function speakerStepUpdate(
  flow: FlowPublic,
  after: FlowStep,
  option: StepKindOption,
  names: { step: string; fieldLabel: string; fieldName: string }
): EditorUpdate {
  const fields = formFieldsOf(flow.metadata_json);
  const existing = participantsFieldOf(fields);
  const participants: FormFieldDraft = existing ?? {
    key: "participants",
    name: suggestedFieldName(
      names.fieldName,
      fields.map((candidate) => candidate.name)
    ),
    label: names.fieldLabel,
    type: "list",
    required: false,
    options: [],
    nameEdited: true
  };
  const update = newStepUpdate(flow, after.step_order + 1, option, {
    name: uniqueStepName(flow, names.step)
  });
  const [step] = update.new_steps ?? [];
  if (!step) return update;
  const configuration = step.configuration;
  configuration.output_config = withSpeakerMapping(configuration.output_config, {
    participantsField: participants.name,
    speakerCountField: null,
    inferNames: false
  });
  if (!existing) {
    update.definition = {
      ...update.definition,
      metadata_json: metadataWithSettings(
        flow.metadata_json,
        [...fields, participants],
        evidenceExportAllowed(flow.metadata_json)
      )
    };
  }
  return update;
}
