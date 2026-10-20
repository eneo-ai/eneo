// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FlowStep, LlmStep } from "../types";
import { buildStep, changedFields, useStepDraft } from "./use-step-draft";

const llm: LlmStep = {
  kind: "llm",
  key: "summary",
  name: "Sammanfatta",
  prompt: "Lista besluten.",
  input: "{{previous}}",
  output: { type: "json", schema: { type: "object", properties: { decisions: {} } } }
};

describe("useStepDraft", () => {
  it("tracks which fields changed and resets them", () => {
    const { result } = renderHook(() => useStepDraft(llm));
    expect(result.current.dirty).toEqual([]);
    act(() => result.current.update({ prompt: "Lista besluten kort.", name: "Sammanfatta" }));
    expect(result.current.dirty).toEqual(["prompt"]);
    act(() => result.current.reset());
    expect(result.current.dirty).toEqual([]);
  });

  it("keeps a JSON field as text until it parses, and builds the step from it", () => {
    const { result } = renderHook(() => useStepDraft(llm));
    act(() => result.current.setJson("output", "{ not json"));
    expect(result.current.draft.json.output.error).toBe("invalid");
    expect(result.current.built).toBe(null);
    expect(result.current.dirty).toEqual(["output"]);
    act(() => result.current.setJson("output", '{"type": "object", "properties": {"a": {}}}'));
    expect(result.current.draft.json.output.error).toBe(null);
    const built = result.current.built as LlmStep;
    expect(built.output).toEqual({
      type: "json",
      schema: { type: "object", properties: { a: {} } }
    });
    expect(result.current.dirty).toEqual(["output"]);
    act(() => result.current.setJson("output", "[1]"));
    expect(result.current.draft.json.output.error).toBe("not_object");
  });

  it("takes one field from another version of the step", () => {
    const theirs: LlmStep = { ...llm, prompt: "Assistentens prompt", model_id: "m-2" };
    const { result } = renderHook(() => useStepDraft(llm));
    act(() => result.current.restoreFrom("prompt", theirs));
    expect(result.current.draft.step.kind === "llm" && result.current.draft.step.prompt).toBe(
      "Assistentens prompt"
    );
    expect(result.current.dirty).toEqual(["prompt"]);
  });
});

describe("changedFields / buildStep", () => {
  it("compares steps field by field and treats a kind change as everything", () => {
    const edited: FlowStep = { ...llm, name: "Ny", model_kwargs: { temperature: 0 } };
    expect(changedFields(edited, llm)).toEqual(["name", "model_kwargs"]);
    expect(changedFields({ kind: "compose", key: "x", name: "x", template: "" }, llm)).toEqual([
      "name",
      "description",
      "template"
    ]);
    const compose: FlowStep = { kind: "compose", key: "x", name: "x", template: "{{previous}}" };
    expect(
      buildStep({
        step: compose,
        json: { output: { text: "", error: null }, arguments: { text: "", error: null } }
      })
    ).toBe(compose);
  });
});
