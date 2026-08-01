import type { components } from "@eneo/eneo-js";

export type StructuredQuestionOption = components["schemas"]["StructuredQuestionOptionPayload"];

export type StructuredQuestion = components["schemas"]["StructuredQuestionPayload"];

type GeneratedInputField = components["schemas"]["FlowInputFieldIntent"];
export type StructuredInputFieldType = NonNullable<GeneratedInputField["type"]>;

export interface StructuredInputFieldAnswer extends Omit<
  GeneratedInputField,
  "type" | "required" | "options" | "provenance"
> {
  type: StructuredInputFieldType;
  required: boolean;
  options: string[];
}

type StructuredQuestionOptionValue = Exclude<StructuredQuestionOption["value"], undefined>;

export type PersistedStructuredQuestionAnswerMetadata = Omit<
  components["schemas"]["StructuredQuestionAnswerMetadata"],
  "kind" | "selected_values"
> & { selected_values?: StructuredQuestionOptionValue[] | null };

export type StructuredQuestionAnswerMetadata =
  | components["schemas"]["StructuredQuestionAnswerMetadata"]
  | components["schemas"]["RequirementsConfirmationMetadata"];

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
    ...field,
    name: field.name.trim(),
    label: field.label.trim(),
    options:
      field.type === "select" || field.type === "multiselect"
        ? field.options.map((option) => option.trim()).filter(Boolean)
        : []
  }));
  return {
    text: inputFields.map((field) => `${field.label} (${field.name})`).join(", "),
    questionAnswer: {
      kind: "structured_question_answer",
      question_id: question.question_id,
      input_fields: inputFields
    }
  };
}
