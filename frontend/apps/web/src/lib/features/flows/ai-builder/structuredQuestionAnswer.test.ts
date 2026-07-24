import { describe, expect, it } from "vitest";

import {
  buildStructuredQuestionCustomAnswer,
  buildStructuredQuestionInputFieldsAnswer,
  buildStructuredQuestionSelection,
  getStructuredQuestionOptionKey,
  type StructuredQuestion
} from "./structuredQuestionAnswer";

describe("structured question answer helpers", () => {
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
