import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowAIBuilderQuestion from "./FlowAIBuilderQuestion.svelte";
import type { StructuredQuestion } from "./structuredQuestionAnswer";

afterEach(() => {
  cleanup();
});

function schemaDirectionQuestion(count = 2): StructuredQuestion {
  const candidates = Array.from({ length: count }, (_, index) => ({
    fingerprint: String(index + 1).padStart(64, "0"),
    label: `Schema ${index + 1}`
  }));
  return {
    question_id: "schema_direction",
    question: "How should the schemas be used?",
    selection_mode: "multi",
    allow_custom: false,
    requires_confirm: true,
    options: [
      ...candidates.flatMap(({ fingerprint, label }) => [
        {
          id: `input:${fingerprint}`,
          value: `input:${fingerprint}`,
          label: `Input — ${label}`
        },
        {
          id: `output:${fingerprint}`,
          value: `output:${fingerprint}`,
          label: `Output — ${label}`
        }
      ]),
      { id: "reference_only", value: "reference_only", label: "Reference only" }
    ]
  };
}

describe("FlowAIBuilderQuestion schema direction", () => {
  it("submits at most one assignment for each boundary", async () => {
    const onanswer = vi.fn();
    const question = schemaDirectionQuestion();
    render(FlowAIBuilderQuestion, { question, onanswer });

    await fireEvent.click(screen.getByRole("checkbox", { name: "Input — Schema 1" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Output — Schema 1" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Input — Schema 2" }));
    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_question_confirm() }));

    expect(onanswer).toHaveBeenCalledOnce();
    expect(onanswer.mock.calls[0]?.[0].questionAnswer.selected_values).toEqual([
      question.options[1].value,
      question.options[2].value
    ]);
  });

  it("keeps large candidate sets searchable without rendering every choice", async () => {
    render(FlowAIBuilderQuestion, { question: schemaDirectionQuestion(100) });

    expect(screen.getAllByRole("checkbox")).toHaveLength(24);
    expect(screen.getByRole("checkbox", { name: "Input — Schema 1" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Output — Schema 1" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Reference only" })).toBeTruthy();
    const filter = screen.getByRole("searchbox", {
      name: m.ai_builder_question_schema_filter()
    });
    await fireEvent.input(filter, { target: { value: "Schema 100" } });

    expect(screen.getByRole("checkbox", { name: "Input — Schema 100" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Output — Schema 100" })).toBeTruthy();
  });

  it("keeps filtered-out assignments visible and removable before confirmation", async () => {
    const onanswer = vi.fn();
    const question = schemaDirectionQuestion(15);
    render(FlowAIBuilderQuestion, { question, onanswer });

    await fireEvent.click(screen.getByRole("checkbox", { name: "Output — Schema 1" }));
    const filter = screen.getByRole("searchbox", {
      name: m.ai_builder_question_schema_filter()
    });
    await fireEvent.input(filter, { target: { value: "Schema 15" } });
    const selectedOutput = screen.getByRole("checkbox", { name: "Output — Schema 1" });
    expect(selectedOutput.getAttribute("aria-checked")).toBe("true");

    await fireEvent.click(selectedOutput);
    await fireEvent.click(screen.getByRole("checkbox", { name: "Input — Schema 15" }));
    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_question_confirm() }));

    expect(onanswer.mock.calls[0]?.[0].questionAnswer.selected_values).toEqual([
      question.options[28].value
    ]);
  });
});

function singleChoiceQuestion(): StructuredQuestion {
  return {
    question_id: "output_format",
    question: "What should the flow produce?",
    selection_mode: "single",
    allow_custom: false,
    requires_confirm: true,
    options: [
      { id: "pdf", value: "pdf", label: "PDF" },
      { id: "text", value: "text", label: "Text" },
      { id: "table", value: "table", label: "Table" }
    ]
  };
}

describe("FlowAIBuilderQuestion single choice keyboard", () => {
  it("is one tab stop whose arrow keys move the selection", async () => {
    render(FlowAIBuilderQuestion, { question: singleChoiceQuestion() });

    const radios = screen.getAllByRole("radio");
    expect(radios.map((radio) => radio.getAttribute("tabindex"))).toEqual(["0", "-1", "-1"]);

    await fireEvent.keyDown(radios[0]!, { key: "ArrowDown" });
    expect(radios[1]!.getAttribute("aria-checked")).toBe("true");
    expect(radios.map((radio) => radio.getAttribute("tabindex"))).toEqual(["-1", "0", "-1"]);

    await fireEvent.keyDown(radios[1]!, { key: "End" });
    expect(radios[2]!.getAttribute("aria-checked")).toBe("true");

    await fireEvent.keyDown(radios[2]!, { key: "ArrowRight" });
    expect(radios[0]!.getAttribute("aria-checked")).toBe("true");
    expect(radios.filter((radio) => radio.getAttribute("tabindex") === "0")).toHaveLength(1);
  });

  it("leaves every row of a multi-select group tabbable", () => {
    render(FlowAIBuilderQuestion, { question: schemaDirectionQuestion() });

    for (const row of screen.getAllByRole("checkbox")) {
      expect(row.getAttribute("tabindex")).toBeNull();
    }
  });
});

function metadataQuestion(): StructuredQuestion {
  return {
    question_id: "runtime_metadata_field_details",
    question: "Which fields should the user fill in?",
    selection_mode: "single",
    allow_custom: false,
    requires_confirm: true,
    input_field_collection: true,
    options: [
      { id: "interpret_input", label: "Use it to read the input", value: "interpret_input" }
    ]
  };
}

describe("FlowAIBuilderQuestion runtime metadata fields", () => {
  it("requires and submits one purpose per field from the question options", async () => {
    const onanswer = vi.fn();
    const question: StructuredQuestion = {
      question_id: "runtime_metadata_field_details",
      question: "Which fields should the user fill in?",
      selection_mode: "single",
      allow_custom: false,
      requires_confirm: true,
      input_field_collection: true,
      options: [
        {
          id: "interpret_input",
          label: "Use it to understand the input",
          value: "interpret_input"
        },
        {
          id: "shape_result",
          label: "Use it to shape the final result",
          value: "shape_result"
        },
        {
          id: "whole_flow",
          label: "Use it throughout the flow",
          value: "whole_flow"
        }
      ]
    };
    render(FlowAIBuilderQuestion, { question, onanswer });

    // The runtime name follows the label; nobody types it.
    await fireEvent.input(screen.getByLabelText(m.ai_builder_question_field_label()), {
      target: { value: "Case id" }
    });
    const confirm = screen.getByRole("button", { name: m.ai_builder_question_confirm() });
    // Reachable by keyboard while unavailable, so aria carries the state.
    expect(confirm.getAttribute("aria-disabled")).toBe("true");

    await fireEvent.change(screen.getByLabelText(m.ai_builder_question_field_purpose()), {
      target: { value: "interpret_input" }
    });
    expect(confirm.getAttribute("aria-disabled")).toBe("false");
    await fireEvent.click(confirm);

    expect(onanswer).toHaveBeenCalledWith({
      text: "Case id (case_id)",
      questionAnswer: {
        kind: "structured_question_answer",
        question_id: "runtime_metadata_field_details",
        input_fields: [
          {
            value: {
              name: "case_id",
              label: "Case id",
              type: "text",
              required: false,
              options: []
            },
            purpose: "interpret_input"
          }
        ]
      }
    });
  });

  it("keeps a runtime name off the label the product reserves, and off a sibling", async () => {
    render(FlowAIBuilderQuestion, { question: metadataQuestion() });

    // "Text" is reserved as a runtime key, so the shared helper prefixes it.
    await fireEvent.input(screen.getByLabelText(m.ai_builder_question_field_label()), {
      target: { value: "Text" }
    });
    await fireEvent.click(screen.getByLabelText(m.ai_builder_question_show_technical()));
    expect(
      (screen.getByLabelText(m.ai_builder_question_field_name()) as HTMLInputElement).value
    ).toBe("user_text");

    await fireEvent.click(screen.getByRole("button", { name: m.ai_builder_question_field_add() }));
    const labels = screen.getAllByLabelText(m.ai_builder_question_field_label());
    await fireEvent.input(labels[1]!, { target: { value: "Text" } });
    const names = screen.getAllByLabelText(m.ai_builder_question_field_name());
    expect((names[1] as HTMLInputElement).value).toBe("user_text_2");
  });

  it("hands the name to the user once they type it, and refuses one the server would", async () => {
    render(FlowAIBuilderQuestion, { question: metadataQuestion() });

    await fireEvent.input(screen.getByLabelText(m.ai_builder_question_field_label()), {
      target: { value: "Personnummer" }
    });
    await fireEvent.click(screen.getByLabelText(m.ai_builder_question_show_technical()));
    const name = screen.getByLabelText(m.ai_builder_question_field_name()) as HTMLInputElement;
    expect(name.value).toBe("personnummer");

    // Typed by hand: the label no longer drives it.
    await fireEvent.input(name, { target: { value: "flow_input" } });
    await fireEvent.input(screen.getByLabelText(m.ai_builder_question_field_label()), {
      target: { value: "Sökandes personnummer" }
    });
    expect(name.value).toBe("flow_input");

    // And a name the server refuses cannot be sent from here either.
    await fireEvent.change(screen.getByLabelText(m.ai_builder_question_field_purpose()), {
      target: { value: "interpret_input" }
    });
    expect(
      screen
        .getByRole("button", { name: m.ai_builder_question_confirm() })
        .getAttribute("aria-disabled")
    ).toBe("true");
  });
});
