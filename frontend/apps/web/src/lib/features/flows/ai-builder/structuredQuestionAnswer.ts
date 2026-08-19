import type { components } from "@eneo/eneo-js";

export type StructuredQuestionOption = components["schemas"]["StructuredQuestionOptionPayload"];

export type StructuredQuestion = components["schemas"]["StructuredQuestionPayload"];

type GeneratedInputField = components["schemas"]["FlowInputFieldIntent"];
export type StructuredInputFieldType = NonNullable<GeneratedInputField["type"]>;
export type StructuredInputFieldPurpose =
  components["schemas"]["RuntimeMetadataFieldAnswer"]["purpose"];

export interface StructuredInputFieldValue extends Omit<
  GeneratedInputField,
  "type" | "required" | "options" | "provenance"
> {
  type: StructuredInputFieldType;
  required: boolean;
  options: string[];
}

export interface StructuredInputFieldAnswer {
  value: StructuredInputFieldValue;
  purpose: StructuredInputFieldPurpose;
}

export function isStructuredInputFieldPurpose(
  value: StructuredQuestionOption["value"] | ""
): value is StructuredInputFieldPurpose {
  return value === "interpret_input" || value === "shape_result" || value === "whole_flow";
}

type StructuredQuestionOptionValue = Exclude<StructuredQuestionOption["value"], undefined>;

export type PersistedStructuredQuestionAnswerMetadata = Omit<
  components["schemas"]["StructuredQuestionAnswerMetadata"],
  "kind" | "selected_values"
> & { selected_values?: StructuredQuestionOptionValue[] | null };

/** What the client sends. The replay shape (`…Metadata`) carries the server's
 *  own provenance, so it is read, never sent. */
export type StructuredQuestionAnswerMetadata =
  | components["schemas"]["StructuredQuestionAnswerRequest"]
  | components["schemas"]["RequirementsConfirmationMetadata"]
  | components["schemas"]["DelegatedQuestionAnswerRequest"]
  // Editing the content list is an answer about the contract rather than about
  // a question, and travels the same typed path.
  | components["schemas"]["NamedContentFieldsEditRequest"];

/** The user handing this question back to Eneo, naming no option. */
export function delegatedQuestionAnswer(
  questionId: string,
  uiLanguage: string
): components["schemas"]["DelegatedQuestionAnswerRequest"] {
  return {
    kind: "delegated_question_answer",
    question_id: questionId,
    ui_language: uiLanguage
  };
}

export interface StructuredQuestionAnswerPayload {
  text: string;
  questionAnswer: StructuredQuestionAnswerMetadata;
}

export function getStructuredQuestionOptionKey(option: StructuredQuestionOption): string {
  return option.id ?? option.label;
}

export function toggleStructuredQuestionOption(
  question: StructuredQuestion,
  selectedKeys: ReadonlySet<string>,
  option: StructuredQuestionOption
): Set<string> {
  const optionKey = getStructuredQuestionOptionKey(option);
  const next = new Set(selectedKeys);
  if (next.delete(optionKey)) return next;

  if (question.question_id === "schema_direction") {
    if (optionKey === "reference_only") return new Set([optionKey]);

    next.delete("reference_only");
    const boundary = optionKey.split(":", 1)[0];
    if (boundary === "input" || boundary === "output") {
      for (const selectedKey of next) {
        if (selectedKey.startsWith(`${boundary}:`)) next.delete(selectedKey);
      }
    }
  }
  next.add(optionKey);
  return next;
}

export function buildStructuredQuestionSelection(
  question: StructuredQuestion,
  selectedOptions: StructuredQuestionOption[]
): StructuredQuestionAnswerPayload {
  return {
    text: selectedOptions.map((option) => option.label).join(", "),
    questionAnswer: {
      kind: "structured_question_answer",
      question_id: question.question_id,
      selected_option_ids: selectedOptions
        .map((option) => option.id)
        .filter((id): id is string => Boolean(id)),
      selected_values: selectedOptions.flatMap((option) =>
        option.value === undefined ? [] : [option.value]
      )
    }
  };
}

export function buildStructuredQuestionCustomAnswer(
  question: StructuredQuestion,
  customValue: string
): StructuredQuestionAnswerPayload {
  return {
    text: customValue,
    questionAnswer: {
      kind: "structured_question_answer",
      question_id: question.question_id,
      custom_value: customValue
    }
  };
}

export function buildStructuredQuestionInputFieldsAnswer(
  question: StructuredQuestion,
  fields: StructuredInputFieldAnswer[]
): StructuredQuestionAnswerPayload {
  const inputFields = fields.map((field) => ({
    value: {
      ...field.value,
      name: field.value.name.trim(),
      label: field.value.label.trim(),
      options:
        field.value.type === "select" || field.value.type === "multiselect"
          ? field.value.options.map((option) => option.trim()).filter(Boolean)
          : []
    },
    purpose: field.purpose
  }));
  return {
    text: inputFields.map((field) => `${field.value.label} (${field.value.name})`).join(", "),
    questionAnswer: {
      kind: "structured_question_answer",
      question_id: question.question_id,
      input_fields: inputFields
    }
  };
}
