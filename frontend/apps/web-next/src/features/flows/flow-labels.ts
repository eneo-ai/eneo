import type { Schema } from "@/lib/api/models";
import type { FlowStep } from "./flows-api";
import { stepName, type StepRead } from "./flow-steps";

type Translate = (key: string, values?: Record<string, string | number>) => string;

const INPUT_TYPE_KEYS: Record<Schema<"FlowInputType">, string> = {
  text: "flows_input_type_text",
  json: "flows_input_type_json",
  image: "flows_input_type_image",
  audio: "flows_input_type_audio",
  document: "flows_input_type_document",
  file: "flows_input_type_file",
  any: "flows_input_type_any"
};

const OUTPUT_TYPE_KEYS: Record<Schema<"FlowOutputType">, string> = {
  text: "flows_output_type_text",
  json: "flows_output_type_json",
  pdf: "flows_output_type_pdf",
  docx: "flows_output_type_docx"
};

const OUTPUT_MODE_KEYS: Record<Schema<"FlowOutputMode">, string> = {
  pass_through: "flows_output_mode_pass_through",
  compose_text: "flows_output_mode_compose_text",
  copy_input: "flows_output_mode_copy_input",
  http_post: "flows_output_mode_http_post",
  transcribe_only: "flows_output_mode_transcribe_only",
  template_fill: "flows_output_mode_template_fill",
  render_verbatim: "flows_output_mode_render_verbatim",
  speaker_mapping: "flows_output_mode_speaker_mapping"
};

/** A value the generated types do not know yet shows as it is, never as a missing key. */
function labelOf<K extends string>(keys: Record<K, string>, value: string, t: Translate): string {
  const key = keys[value as K] as string | undefined;
  return key ? t(key) : value;
}

/** "Steg 2: Sammanfatta", or "Steg 2" for a step without a name. */
export function stepLabel(step: Pick<FlowStep, "user_description" | "step_order">, t: Translate) {
  const name = stepName(step);
  return name
    ? t("flows_step_label", { order: step.step_order, name })
    : t("flows_step_label_unnamed", { order: step.step_order });
}

export function inputTypeLabel(value: string, t: Translate): string {
  return labelOf(INPUT_TYPE_KEYS, value, t);
}

/** What a step produces: its output type and how it makes it ("Text · Bearbetas med AI"). */
export function producesLabel(step: Pick<FlowStep, "output_type" | "output_mode">, t: Translate) {
  return t("flows_step_produces_value", {
    type: labelOf(OUTPUT_TYPE_KEYS, step.output_type, t),
    mode: labelOf(OUTPUT_MODE_KEYS, step.output_mode, t)
  });
}

export function readLabel(read: StepRead, t: Translate): string {
  switch (read.kind) {
    case "flow_input":
      return t("flows_read_flow_input");
    case "http":
      return t("flows_read_http");
    case "tool":
      return t("flows_read_tool");
    case "step":
      return read.step
        ? stepLabel(read.step, t)
        : t("flows_read_step_missing", { order: read.order });
  }
}
