import { refusalMessage, type Translator } from "./field-problems";
import { withTranscriptionEnabled } from "./step-draft";
import { stepLabel } from "./step-labels";
import type { components } from "@/lib/api/schema";
import type { EditorUpdate, FlowPublic, StepPatch } from "./step-types";

/**
 * The kinds of step the add dialog offers. Which kinds may stand at a place,
 * and the configuration each starts with there, are the flow core's answer
 * (`GET /flows/{id}/step-kinds/`, judged by the draft save itself); this
 * module only turns an answer into the editor update that adds the step and
 * into sentences a person can act on.
 */

type Schemas = components["schemas"];

export type StepKind = Schemas["FlowStepKind"];
/** The kinds at one place: an insertion (`step_id` null) or a saved step. */
export type StepKindPlace = Schemas["FlowStepKindPlacePublic"];
export type StepKindOption = Schemas["FlowStepKindOptionPublic"];
export type StepKindRefusal = Schemas["FlowStepKindRefusalPublic"];

export type DocumentFormat = "docx" | "pdf";

export type NewStepOptions = {
  name: string;
  format?: DocumentFormat;
  url?: string;
  tool?: { mcp_server_id: string; tool_id: string; arguments: Record<string, unknown> } | null;
};

/** The option of `kind` at `place`, or null when the place does not offer it. */
export function kindOption(
  place: Pick<StepKindPlace, "options"> | null | undefined,
  kind: StepKind
): StepKindOption | null {
  return place?.options.find((option) => option.kind === kind) ?? null;
}

/**
 * What the author entered, put into the core's starting configuration: the
 * document format, the address of an HTTP kind and the tool of a tool kind.
 */
function enteredConfiguration(option: StepKindOption, entered: NewStepOptions): StepPatch {
  const configuration: StepPatch = { ...option.configuration };
  switch (option.kind) {
    case "document":
      configuration.output_type = entered.format ?? "docx";
      break;
    case "fetch_http":
      configuration.input_config = { ...option.configuration.input_config, url: entered.url ?? "" };
      break;
    case "send_http":
      configuration.output_config = {
        ...option.configuration.output_config,
        url: entered.url ?? ""
      };
      break;
    case "tool":
      configuration.input_config = entered.tool ? { tool: { ...entered.tool } } : null;
      break;
    default:
      break;
  }
  return configuration;
}

/**
 * The editor update that adds a step of `option`'s kind at `position`
 * (1-based), fenced on the draft's revision: the new step with the core's
 * configuration and an empty assistant, every saved step in order with the
 * new one at `position`, the saved steps the core edits too (a step added
 * first takes the run's input over) and transcription turned on when the core
 * says the step needs it.
 */
export function newStepUpdate(
  flow: Pick<FlowPublic, "steps" | "draft_revision" | "metadata_json">,
  position: number,
  option: StepKindOption,
  entered: NewStepOptions
): EditorUpdate {
  const saved = [...flow.steps].sort((left, right) => left.step_order - right.step_order);
  const slots: NonNullable<EditorUpdate["step_order"]> = saved.map((step) => ({
    step_id: step.id
  }));
  slots.splice(position - 1, 0, { new_step: 0 });
  const update: EditorUpdate = {
    expected_revision: flow.draft_revision,
    definition: option.turns_on_transcription
      ? { metadata_json: withTranscriptionEnabled(flow.metadata_json) }
      : {},
    new_steps: [
      {
        name: entered.name.trim(),
        configuration: enteredConfiguration(option, entered),
        assistant: {}
      }
    ],
    step_order: slots
  };
  if (option.step_edits.length > 0) {
    update.step_edits = option.step_edits.map((edit) => ({
      step_id: edit.step_id,
      changes: edit.changes
    }));
  }
  return update;
}

/** Where a refusal sits relative to a step added at `position`. */
type Relation = "new" | "before" | "after" | "other" | "flow";

function relationOf(refusal: StepKindRefusal, position: number): Relation {
  if (refusal.step_order === null) return "flow";
  if (refusal.step_id === null && refusal.step_order === position) return "new";
  // Refusals number the steps as after the change: the step after is one further down.
  if (refusal.step_order === position - 1) return "before";
  if (refusal.step_order === position + 1) return "after";
  return "other";
}

const FIRST_ONLY = new Set([
  "typed_io_flow_input_position_invalid",
  "typed_io_invalid_input_source_position",
  "typed_io_multiple_flow_input_steps"
]);
const UPLOADS_STAY_FIRST = new Set([
  ...FIRST_ONLY,
  "typed_io_audio_source_unsupported",
  "typed_io_document_source_unsupported",
  "typed_io_file_source_unsupported"
]);

/** The add dialog's own sentence for the refusals it meets most, by code and place. */
function placeKey(code: string | null, relation: Relation): string | null {
  if (!code) return null;
  if (code === "flow_http_post_output_must_be_terminal") {
    if (relation === "new") return "flow_step_editor_kind_block_must_be_last";
    if (relation === "before") return "flow_step_editor_kind_block_after_outbound_step";
  }
  if (relation === "new" && FIRST_ONLY.has(code)) return "flow_step_editor_kind_block_first_only";
  if (relation === "new" && code === "typed_io_missing_previous_step") {
    return "flow_step_editor_kind_block_needs_step_before";
  }
  if (relation === "after" && code === "typed_io_incompatible_type_chain") {
    return "flow_step_editor_kind_block_next_step_cannot_read";
  }
  if (relation === "after" && UPLOADS_STAY_FIRST.has(code)) {
    return "flow_step_editor_kind_block_first_step_takes_uploads";
  }
  return null;
}

/**
 * Why a kind cannot be added at `position`, in plain text from the refusal's
 * typed codes: the dialog's sentence for the place when it has one, else the
 * catalog's sentence for the code, naming the step it is about by its name
 * and its place in the flow as it stands.
 */
export function kindRefusalText(
  refusal: StepKindRefusal,
  position: number,
  flow: Pick<FlowPublic, "steps">,
  t: Translator
): string {
  const relation = relationOf(refusal, position);
  const code = refusal.issue_code ?? refusal.code;
  const key = placeKey(code, relation);
  if (key) return t(key);
  const message =
    refusalMessage(refusal.issue_code, t) ??
    refusalMessage(refusal.code, t) ??
    t("flow_step_editor_kind_block_refused");
  if (relation === "new" || relation === "flow") return message;
  const step =
    flow.steps.find((candidate) => refusal.step_id !== null && candidate.id === refusal.step_id) ??
    null;
  if (!step) return message;
  return t("flow_step_editor_other_step_problem", {
    step: stepLabel(step.step_order, step.user_description, t),
    message
  });
}

/** A name for the new step that no other step has: the base, then "base 2", "base 3", … */
export function uniqueStepName(flow: Pick<FlowPublic, "steps">, base: string): string {
  const taken = new Set(
    flow.steps.map((step) => (step.user_description ?? "").trim().toLocaleLowerCase())
  );
  if (!taken.has(base.trim().toLocaleLowerCase())) return base;
  for (let index = 2; ; index += 1) {
    const candidate = `${base} ${index}`;
    if (!taken.has(candidate.toLocaleLowerCase())) return candidate;
  }
}

export function stepNameTaken(
  flow: Pick<FlowPublic, "steps">,
  name: string,
  exceptStepId?: string
) {
  const key = name.trim().toLocaleLowerCase();
  return flow.steps.some(
    (step) =>
      step.id !== exceptStepId && (step.user_description ?? "").trim().toLocaleLowerCase() === key
  );
}
