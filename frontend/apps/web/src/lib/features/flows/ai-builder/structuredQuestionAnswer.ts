export interface StructuredQuestionOption {
  id?: string | null;
  label: string;
  value?: unknown;
  description?: string | null;
}

export interface StructuredQuestion {
  question_id: string;
  question: string;
  options: StructuredQuestionOption[];
  selection_mode: "single" | "multi";
  allow_custom: boolean;
  requires_confirm?: boolean;
}

export interface StructuredQuestionAnswerMetadata {
  question_id?: string | null;
  selected_option_ids?: string[];
  selected_values?: unknown[];
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
      selected_values: selectedOptions
        .filter((option) => option.value !== undefined)
        .map((option) => option.value)
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
