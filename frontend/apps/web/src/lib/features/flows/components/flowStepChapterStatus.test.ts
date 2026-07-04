import { describe, it, expect } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import {
  getChapterWhatStatus,
  getChapterOutputStatus,
  getChapterControlStatus,
  getChapterAdvancedStatus
} from "./flowStepChapterStatus";

function step(partial: Partial<FlowStep>): FlowStep {
  return {
    input_source: "previous_step",
    input_type: "text",
    output_type: "text",
    output_mode: "pass_through",
    step_order: 2,
    ...partial
  } as unknown as FlowStep;
}

describe("getChapterWhatStatus", () => {
  it("renders input and output type labels joined by an arrow", () => {
    expect(getChapterWhatStatus(step({ input_type: "json", output_type: "docx" }))).toBe(
      `${m.flow_type_json()} → ${m.flow_output_type_docx()}`
    );
  });

  it("falls back to the raw value for an unknown type", () => {
    expect(getChapterWhatStatus(step({ input_type: "mystery" as never }))).toBe(
      `mystery → ${m.flow_output_type_text()}`
    );
  });
});

describe("getChapterOutputStatus", () => {
  it("appends the mode label after the output label when a mode label exists", () => {
    expect(
      getChapterOutputStatus(step({ output_type: "text", output_mode: "transcribe_only" }))
    ).toBe(`${m.flow_output_type_text()} · ${m.flow_output_mode_transcribe_only()}`);
  });

  it("shows only the output label when the mode has no matching label", () => {
    expect(
      getChapterOutputStatus(step({ output_type: "json", output_mode: "unknown" as never }))
    ).toBe(m.flow_output_type_json());
  });
});

describe("getChapterControlStatus", () => {
  it("reports inheritance when no classification override is set", () => {
    expect(getChapterControlStatus(step({ output_classification_override: null }))).toBe(
      m.flow_step_security_inherit()
    );
    expect(getChapterControlStatus(step({ output_classification_override: undefined }))).toBe(
      m.flow_step_security_inherit()
    );
  });

  it("renders a K-prefixed level when an override is set, including level 0", () => {
    expect(getChapterControlStatus(step({ output_classification_override: 3 }))).toBe("K3");
    expect(getChapterControlStatus(step({ output_classification_override: 0 }))).toBe("K0");
  });
});

describe("getChapterAdvancedStatus", () => {
  it("reports the default label when neither contract is set", () => {
    expect(getChapterAdvancedStatus(step({ input_contract: null, output_contract: null }))).toBe(
      m.flow_chapter_advanced_default()
    );
  });

  it("reports custom contracts when the input contract is set", () => {
    expect(getChapterAdvancedStatus(step({ input_contract: { type: "object" } }))).toBe(
      m.flow_chapter_advanced_custom()
    );
  });

  it("reports custom contracts when the output contract is set", () => {
    expect(getChapterAdvancedStatus(step({ output_contract: { type: "object" } }))).toBe(
      m.flow_chapter_advanced_custom()
    );
  });
});
