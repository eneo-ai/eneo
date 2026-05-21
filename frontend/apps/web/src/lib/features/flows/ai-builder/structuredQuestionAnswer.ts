import type { components } from "@intric/intric-js";

export type StructuredQuestionOption = components["schemas"]["StructuredQuestionOptionPayload"];

export type StructuredQuestion = components["schemas"]["StructuredQuestionPayload"];

type StructuredQuestionOptionValue = Exclude<StructuredQuestionOption["value"], undefined>;

export interface StructuredQuestionAnswerMetadata {
  question_id?: string | null;
  selected_option_ids?: string[];
  selected_values?: StructuredQuestionOptionValue[];
  custom_value?: string;
  requirements_confirmed?: boolean;
  requirements_version?: string;
}

export interface StructuredQuestionAnswerPayload {
  text: string;
  questionAnswer: StructuredQuestionAnswerMetadata;
}

export function getStructuredQuestionOptionKey(option: StructuredQuestionOption): string {
  return option.id ?? option.label;
}

export function buildStructuredQuestionSelection(
  question: StructuredQuestion,
  selectedOptions: StructuredQuestionOption[]
): StructuredQuestionAnswerPayload {
  return {
    text: selectedOptions.map((option) => option.label).join(", "),
    questionAnswer: {
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
      question_id: question.question_id,
      custom_value: customValue
    }
  };
}
