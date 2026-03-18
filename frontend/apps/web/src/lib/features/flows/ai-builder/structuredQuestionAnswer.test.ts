import { describe, expect, it } from "vitest";

import {
  buildStructuredQuestionCustomAnswer,
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
          value: { mode: "single" }
        },
        {
          id: "multi",
          label: "Multiple PDFs",
          value: { mode: "multi" }
        }
      ]
    };

    const result = buildStructuredQuestionSelection(question, [question.options[0]]);

    expect(result.text).toBe("One PDF");
    expect(result.questionAnswer).toEqual({
      question_id: "pdf_count",
      selected_option_ids: ["single"],
      selected_values: [{ mode: "single" }]
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
      question_id: "docx_template",
      custom_value: "Use the board-report template"
    });
  });
});
