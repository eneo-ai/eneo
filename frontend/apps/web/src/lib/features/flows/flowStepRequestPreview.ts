import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import {
  getFlowFormFieldLabel,
  PREVIOUS_STEP_ALIAS,
  type FlowFormSchemaMetadata
} from "./flowFormSchema";
import { getTextProcessingMode } from "./flowTextProcessingConfig";
import {
  parsePromptSegments,
  type VariableCategory,
  type VariableClassificationContext
} from "./flowVariableTokens";
import { reviewFieldLabel, reviewSchema } from "./structuredReview";

/**
 * What the request preview shows for one step: the template text with every
 * `{{ token }}` named in words, and what the answer must contain. Labels only;
 * validity and colour come from the editor's own classification.
 */
export type TemplateSegment =
  | { kind: "text"; value: string }
  | { kind: "variable"; token: string; label: string; category: VariableCategory };

const STRUCTURED_FIELD_TOKEN = /^step_(\d+)\.output\.structured\.(.+)$/;
// `step_N` is the whole step record (input, output, status); only its answer
// text is "the answer". Other paths keep their token.
const STEP_ANSWER_TOKEN = /^step_(\d+)\.output\.text$/;

function variableLabel(
  token: string,
  category: VariableCategory,
  context: VariableClassificationContext,
  fieldLabels: Map<string, string>
): string {
  // An invalid reference stays raw so the red chip shows what is wrong.
  if (category === "unknown") return token;
  if (category === "field") {
    const name = token.startsWith("flow_input.") ? token.slice("flow_input.".length) : token;
    return fieldLabels.get(name) ?? name;
  }
  // Only the upload's text is "the uploaded material"; its file ids, length
  // and format are other values and keep their token.
  if (token === "step_input.text") return m.flow_variable_upload_label();
  if (token === "flow_input.text") return m.flow_variable_flow_input_text_label();
  if (token === "section_index") return m.flow_variable_section_index_label();
  if (token === "transkribering") return m.flow_variable_transcription();
  if (token === PREVIOUS_STEP_ALIAS) return m.flow_variable_previous_step();
  const structured = STRUCTURED_FIELD_TOKEN.exec(token);
  if (structured) {
    return m.flow_request_preview_step_field({ field: structured[2], step: structured[1] });
  }
  const answer = STEP_ANSWER_TOKEN.exec(token);
  if (answer) return m.flow_request_preview_step_answer({ step: answer[1] });
  for (const [order, name] of context.knownStepNames) {
    if (order < context.currentStepOrder && name === token) {
      return m.flow_request_preview_step_answer({ step: order });
    }
  }
  return token;
}

export function describeTemplateSegments(
  text: string,
  context: VariableClassificationContext,
  formSchema?: FlowFormSchemaMetadata
): TemplateSegment[] {
  const fieldLabels = new Map(
    (formSchema?.fields ?? []).map((field) => [field.name.trim(), getFlowFormFieldLabel(field)])
  );
  return parsePromptSegments(text, context).map((segment) =>
    segment.type === "text"
      ? { kind: "text", value: segment.value }
      : {
          kind: "variable",
          token: segment.token,
          label: variableLabel(segment.token, segment.category, context, fieldLabels),
          category: segment.category
        }
  );
}

export type AnswerField = { name: string; label: string; description?: string };

export type AnswerDescription =
  | { kind: "free_text" }
  | { kind: "document"; format: "pdf" | "docx" }
  | { kind: "fields"; perSection: boolean; fields: AnswerField[] };

/** The item schema when the contract is one array of objects (single_mapped_array_key). */
function singleArrayItemSchema(
  properties: Record<string, unknown>
): Record<string, unknown> | null {
  const values = Object.values(properties);
  if (values.length !== 1) return null;
  const array = reviewSchema(values[0]);
  const items = reviewSchema(array.items);
  return array.type === "array" && items.type === "object" ? items : null;
}

export function describeAnswerFields(
  step: Pick<FlowStep, "output_type" | "output_contract" | "input_config">
): AnswerDescription {
  if (step.output_type === "pdf" || step.output_type === "docx") {
    return { kind: "document", format: step.output_type };
  }
  if (step.output_type !== "json") return { kind: "free_text" };

  const properties = reviewSchema(reviewSchema(step.output_contract).properties);
  const itemSchema = singleArrayItemSchema(properties);
  const listed = itemSchema ? reviewSchema(itemSchema.properties) : properties;
  return {
    kind: "fields",
    perSection: itemSchema !== null && getTextProcessingMode(step) === "process_each_section",
    fields: Object.entries(listed).map(([name, value]) => {
      const schema = reviewSchema(value);
      const description = typeof schema.description === "string" ? schema.description.trim() : "";
      return {
        name,
        label: reviewFieldLabel(schema, name),
        ...(description ? { description } : {})
      };
    })
  };
}
