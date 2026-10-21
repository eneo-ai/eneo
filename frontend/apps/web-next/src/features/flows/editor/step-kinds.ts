import {
  defaultHttpConfig,
  FILE_INPUT_TYPES,
  hasUnderlag,
  readRuntimeInput,
  withHttpConfig,
  withRuntimeInput,
  withSpeakerMapping,
  type ToolConfig
} from "./step-configs";
import { transcriptionEnabled, withTranscriptionEnabled } from "./step-draft";
import { chainCompatible, inputTypeForOutput } from "./step-rules";
import type {
  EditorUpdate,
  FlowPublic,
  FlowStep,
  InputType,
  OutputType,
  StepPatch
} from "./step-types";

/**
 * The kinds of step the add dialog offers, and the first configuration of
 * each at a given place in the flow. The configuration is valid where it
 * lands: only step 1 reads what the flow is sent, a later step reads the
 * step before it with a type that step can give, a step that sends over HTTP
 * is last, and so on (`step_chain_rules.py`). Inserting before the first step
 * hands the flow's input over to the new step in the same save.
 */

export const STEP_KINDS = [
  "ai",
  "structured",
  "compose",
  "document",
  "template",
  "transcribe",
  "speakers",
  "review",
  "fetch_http",
  "tool",
  "send_http"
] as const;

export type StepKind = (typeof STEP_KINDS)[number];

export type KindBlock =
  | "first_only"
  | "needs_transcript_before"
  | "needs_step_before"
  | "must_be_last"
  | "next_step_cannot_read"
  | "after_outbound_step"
  | "first_step_takes_uploads";

export type DocumentFormat = "docx" | "pdf";

/** What a kind gives the step after it: its output type. */
export function kindOutputType(kind: StepKind, previous: FlowStep | null, format: DocumentFormat) {
  switch (kind) {
    case "structured":
    case "speakers":
      return "json" satisfies OutputType;
    case "document":
      return format;
    case "template":
      return "docx" satisfies OutputType;
    case "review":
      return previous?.output_type === "json" ? "json" : "text";
    default:
      return "text" satisfies OutputType;
  }
}

function stepAt(flow: Pick<FlowPublic, "steps">, order: number): FlowStep | null {
  return flow.steps.find((step) => step.step_order === order) ?? null;
}

/** Why a kind cannot be added at `position` (1-based), or null when it can. */
export function kindBlock(
  flow: Pick<FlowPublic, "steps">,
  position: number,
  kind: StepKind,
  format: DocumentFormat = "docx"
): KindBlock | null {
  const previous = position > 1 ? stepAt(flow, position - 1) : null;
  const next = stepAt(flow, position);
  if (previous?.output_mode === "http_post") return "after_outbound_step";
  if (position === 1 && next && next.input_source === "flow_input" && takesFiles(next)) {
    return "first_step_takes_uploads";
  }
  if (kind === "transcribe" && position !== 1) return "first_only";
  if (kind === "speakers" && previous?.output_mode !== "transcribe_only") {
    return "needs_transcript_before";
  }
  if (kind === "review" && !previous) return "needs_step_before";
  if (kind === "send_http" && next) return "must_be_last";
  if (
    next &&
    position > 1 &&
    next.input_source === "previous_step" &&
    !hasUnderlag(next.input_bindings) &&
    !chainCompatible(kindOutputType(kind, previous, format), next.input_type)
  ) {
    return "next_step_cannot_read";
  }
  return null;
}

function takesFiles(step: FlowStep): boolean {
  return FILE_INPUT_TYPES.has(step.input_type) || readRuntimeInput(step.input_config).enabled;
}

export type NewStepOptions = {
  name: string;
  format?: DocumentFormat;
  url?: string;
  tool?: ToolConfig | null;
};

/** What the new step reads: the flow's input at step 1, else the step before it. */
function reads(position: number, previous: FlowStep | null, type?: InputType): StepPatch {
  if (position === 1 || !previous)
    return { input_source: "flow_input", input_type: type ?? "text" };
  return {
    input_source: "previous_step",
    input_type: type ?? inputTypeForOutput(previous.output_type)
  };
}

/** The configuration a new step of `kind` starts with at `position`. */
export function initialConfiguration(
  flow: Pick<FlowPublic, "steps">,
  position: number,
  kind: StepKind,
  options: NewStepOptions
): StepPatch {
  const previous = position > 1 ? stepAt(flow, position - 1) : null;
  switch (kind) {
    case "ai":
      return { ...reads(position, previous), output_mode: "pass_through", output_type: "text" };
    case "structured":
      return { ...reads(position, previous), output_mode: "pass_through", output_type: "json" };
    case "compose":
      return {
        ...reads(position, previous, "text"),
        output_mode: "compose_text",
        output_type: "text"
      };
    case "document":
      return {
        ...reads(position, previous, "text"),
        output_mode: "render_verbatim",
        output_type: options.format ?? "docx"
      };
    case "template":
      return {
        ...reads(position, previous, "text"),
        output_mode: "template_fill",
        output_type: "docx"
      };
    case "transcribe":
      return {
        input_source: "flow_input",
        input_type: "audio",
        input_config: withRuntimeInput(null, "audio", { enabled: true, required: true }),
        output_mode: "transcribe_only",
        output_type: "text"
      };
    case "speakers":
      return {
        ...reads(position, previous, "text"),
        output_mode: "speaker_mapping",
        output_type: "json",
        review_policy: { mode: "edit" },
        output_config: withSpeakerMapping(null, {
          participantsField: null,
          speakerCountField: null,
          inferNames: false
        })
      };
    case "review": {
      const json = previous?.output_type === "json";
      return {
        ...reads(position, previous, json ? "json" : "text"),
        output_mode: json ? "copy_input" : "compose_text",
        output_type: json ? "json" : "text",
        review_policy: { mode: "edit" }
      };
    }
    case "fetch_http":
      return {
        input_source: "http_get",
        input_type: "text",
        input_config: withHttpConfig(null, {
          ...defaultHttpConfig("input"),
          url: options.url ?? ""
        }),
        output_mode: "compose_text",
        output_type: "text"
      };
    case "tool":
      return {
        input_source: "tool",
        input_type: "text",
        input_config: options.tool
          ? {
              tool: {
                mcp_server_id: options.tool.mcp_server_id,
                tool_id: options.tool.tool_id,
                arguments: options.tool.arguments
              }
            }
          : null,
        output_mode: "compose_text",
        output_type: "text"
      };
    case "send_http":
      return {
        ...reads(position, previous),
        output_mode: "http_post",
        output_type: "text",
        output_config: withHttpConfig(null, {
          ...defaultHttpConfig("output"),
          url: options.url ?? ""
        })
      };
  }
}

/**
 * The editor update that adds the step: the new step with its configuration
 * and (empty) assistant, every saved step in order with the new one at
 * `position`, and, before the first step, the old first step turned to read
 * the new one. A kind that takes audio turns the flow's transcription on.
 */
export function newStepUpdate(
  flow: FlowPublic,
  position: number,
  kind: StepKind,
  options: NewStepOptions
): EditorUpdate {
  const configuration = initialConfiguration(flow, position, kind, options);
  const saved = [...flow.steps].sort((left, right) => left.step_order - right.step_order);
  const slots: NonNullable<EditorUpdate["step_order"]> = saved.map((step) => ({
    step_id: step.id
  }));
  slots.splice(position - 1, 0, { new_step: 0 });
  const update: EditorUpdate = {
    expected_revision: flow.draft_revision,
    definition: {},
    new_steps: [{ name: options.name.trim(), configuration, assistant: {} }],
    step_order: slots
  };
  const first = position === 1 ? (saved[0] ?? null) : null;
  if (first?.id && first.input_source === "flow_input") {
    const outputType = configuration.output_type ?? "text";
    update.step_edits = [
      {
        step_id: first.id,
        changes: {
          input_source: "previous_step",
          ...(chainCompatible(outputType, first.input_type)
            ? {}
            : { input_type: inputTypeForOutput(outputType) })
        }
      }
    ];
  }
  if (kind === "transcribe" && !transcriptionEnabled(flow.metadata_json)) {
    update.definition = { metadata_json: withTranscriptionEnabled(flow.metadata_json) };
  }
  return update;
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
