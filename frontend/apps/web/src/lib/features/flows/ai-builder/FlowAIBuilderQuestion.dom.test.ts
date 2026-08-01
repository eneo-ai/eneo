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
