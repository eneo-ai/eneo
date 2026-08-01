import { describe, expect, it } from "vitest";

import {
  buildStructuredQuestionCustomAnswer,
  buildStructuredQuestionInputFieldsAnswer,
  buildStructuredQuestionSelection,
  getStructuredQuestionOptionKey,
  toggleStructuredQuestionOption,
  type StructuredQuestion
} from "./structuredQuestionAnswer";

describe("structured question answer helpers", () => {
  const schemaDirectionQuestion: StructuredQuestion = {
    question_id: "schema_direction",
    question: "How should the schemas be used?",
    selection_mode: "multi",
    allow_custom: false,
    requires_confirm: true,
    options: [
      { id: `input:${"a".repeat(64)}`, label: "A as input", value: `input:${"a".repeat(64)}` },
      { id: `input:${"b".repeat(64)}`, label: "B as input", value: `input:${"b".repeat(64)}` },
      { id: `output:${"a".repeat(64)}`, label: "A as output", value: `output:${"a".repeat(64)}` },
      { id: "reference_only", label: "Reference only", value: "reference_only" }
    ]
  };

  it("keeps at most one schema per boundary", () => {
    const firstInput = schemaDirectionQuestion.options[0];
    const secondInput = schemaDirectionQuestion.options[1];
    const output = schemaDirectionQuestion.options[2];

    let selected = toggleStructuredQuestionOption(schemaDirectionQuestion, new Set(), firstInput);
    selected = toggleStructuredQuestionOption(schemaDirectionQuestion, selected, output);
    selected = toggleStructuredQuestionOption(schemaDirectionQuestion, selected, secondInput);

    expect([...selected]).toEqual([
      getStructuredQuestionOptionKey(output),
      getStructuredQuestionOptionKey(secondInput)
    ]);
  });

  it("keeps reference-only exclusive from boundary assignments", () => {
    const input = schemaDirectionQuestion.options[0];
    const output = schemaDirectionQuestion.options[2];
    const referenceOnly = schemaDirectionQuestion.options[3];

    let selected = toggleStructuredQuestionOption(schemaDirectionQuestion, new Set(), input);
    selected = toggleStructuredQuestionOption(schemaDirectionQuestion, selected, output);
    selected = toggleStructuredQuestionOption(schemaDirectionQuestion, selected, referenceOnly);
    expect([...selected]).toEqual(["reference_only"]);

    selected = toggleStructuredQuestionOption(schemaDirectionQuestion, selected, output);
    expect([...selected]).toEqual([getStructuredQuestionOptionKey(output)]);
  });

  it("prefers stable option ids and falls back to labels", () => {
    expect(
      getStructuredQuestionOptionKey({
        id: "single",
        label: "One PDF"
      })
    ).toBe("single");
    expect(
      getStructuredQuestionOptionKey({
        label: "Fallback label"
      })
    ).toBe("Fallback label");
  });

  it("preserves option ids and values for structured selections", () => {
    const question: StructuredQuestion = {
      question_id: "pdf_count",
      question: "How many PDFs?",
      selection_mode: "single",
      allow_custom: true,
      options: [
        {
          id: "single",
          label: "One PDF",
          value: "single"
        },
        {
          id: "multi",
          label: "Multiple PDFs",
          value: "multi"
        }
      ]
    };

    const result = buildStructuredQuestionSelection(question, [question.options[0]]);

    expect(result.text).toBe("One PDF");
    expect(result.questionAnswer).toEqual({
      kind: "structured_question_answer",
      question_id: "pdf_count",
      selected_option_ids: ["single"],
      selected_values: ["single"]
    });
  });

  it("preserves custom answers without inventing option ids", () => {
    const question: StructuredQuestion = {
      question_id: "docx_template",
      question: "Which template should we use?",
      selection_mode: "single",
      allow_custom: true,
      options: [
        { id: "default", label: "Default" },
        { id: "other", label: "Other" }
      ]
    };

    const result = buildStructuredQuestionCustomAnswer(question, "Use the board-report template");

    expect(result.text).toBe("Use the board-report template");
    expect(result.questionAnswer).toEqual({
      kind: "structured_question_answer",
      question_id: "docx_template",
      custom_value: "Use the board-report template"
    });
  });

  it("preserves named field types, requiredness, and choice options", () => {
    const question: StructuredQuestion = {
      question_id: "runtime_metadata_field_details",
      question: "Which fields?",
      selection_mode: "multi",
      allow_custom: false,
      options: [],
      input_field_collection: true
    };

    const result = buildStructuredQuestionInputFieldsAnswer(question, [
      {
        name: " category ",
        label: " Category ",
        type: "multiselect",
        required: true,
        options: ["A", " B "]
      }
    ]);

    expect(result).toEqual({
      text: "Category (category)",
      questionAnswer: {
        kind: "structured_question_answer",
        question_id: "runtime_metadata_field_details",
        input_fields: [
          {
            name: "category",
            label: "Category",
            type: "multiselect",
            required: true,
            options: ["A", "B"]
          }
        ]
      }
    });
  });
});
