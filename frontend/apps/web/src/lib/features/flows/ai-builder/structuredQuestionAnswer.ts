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
  | components["schemas"]["NamedContentFieldsEditRequest"]
  // Reopening an assumption is a command: the server answers it with the
  // canonical question instead of recording an answer.
  | components["schemas"]["ReopenQuestionRequest"]
  // Words typed while a question is open, naming the showing they reply to,
  // or declared a request of their own that sets the question aside.
  | components["schemas"]["QuestionReplyRequest"]
  | components["schemas"]["NewRequestDeclaration"];

export type RequirementsSummaryShowing = Pick<
  components["schemas"]["RequirementsSummaryPayload"],
  "requirements_version" | "instance_token"
>;

/** The showing an answer was given to, echoed back so the server can refuse
 *  an answer to a question or card that has since been replaced. A question
 *  or card shown before tokens existed has none to echo. */
export function shownInstance(instanceToken: string | null | undefined): {
  instance_token?: string;
} {
  return instanceToken ? { instance_token: instanceToken } : {};
}

/** Words or files the user sent while this question was open, as a reply to
 *  this showing of it. Once a question carries a token, the server refuses a
 *  turn that names neither the showing it replies to nor `new_request`; a
 *  question without a token needs no binding. */
export function questionReply(
  question: StructuredQuestion
): components["schemas"]["QuestionReplyRequest"] | null {
  if (!question.instance_token) return null;
  return {
    kind: "question_reply",
    question_id: question.question_id,
    instance_token: question.instance_token
  };
}

/** Words sent past an open question as a request of their own. While a
 *  question with a token is open, the server refuses text that says neither
 *  this nor which showing it replies to. */
export function newRequest(): components["schemas"]["NewRequestDeclaration"] {
  return { kind: "new_request" };
}

/** Whether a retained request can go again as a new turn. A reply names the
 *  question that was open when it was sent; once that turn committed, its
 *  own recorded words closed that question, so the same reply again would
 *  only be refused. */
export function resendsAsNewTurn(
  request: { question_answer?: StructuredQuestionAnswerMetadata | null } | null | undefined
): boolean {
  return request != null && request.question_answer?.kind !== "question_reply";
}

/** The user reopening an assumption Eneo made for them; the server answers
 *  with the canonical question, the assumed value recommended. */
export function reopenQuestionRequest(
  questionId: string,
  summary: RequirementsSummaryShowing
): components["schemas"]["ReopenQuestionRequest"] {
  return {
    kind: "reopen_question",
    question_id: questionId,
    requirements_version: summary.requirements_version,
    ...shownInstance(summary.instance_token)
  };
}

/** The user handing this question back to Eneo, naming no option. */
export function delegatedQuestionAnswer(
  question: StructuredQuestion,
  uiLanguage: string
): components["schemas"]["DelegatedQuestionAnswerRequest"] {
  return {
    kind: "delegated_question_answer",
    question_id: question.question_id,
    ...shownInstance(question.instance_token),
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
      ...shownInstance(question.instance_token),
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
      ...shownInstance(question.instance_token),
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
      ...shownInstance(question.instance_token),
      input_fields: inputFields
    }
  };
}
