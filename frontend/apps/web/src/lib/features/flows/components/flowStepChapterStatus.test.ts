import { describe, it, expect } from "vitest";
import type { FlowStep } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import {
  getChapterInputStatus,
  getChapterTaskStatus,
  getChapterOutputStatus,
  getChapterControlStatus,
  getChapterAdvancedStatus,
  getTechnicalSettingsCount
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

  it("replaces JSON with the plain-language label outside advanced mode", () => {
    expect(
      getChapterOutputStatus(step({ output_type: "json", output_mode: "unknown" as never }), false)
    ).toBe(m.flow_output_type_simple_structured());
  });
});

describe("getChapterControlStatus", () => {
  it("summarizes review and inherited classification", () => {
    expect(
      getChapterControlStatus(step({ output_classification_override: null }), {
        security_level: 2,
        name: "Intern"
      })
    ).toBe(`${m.flow_step_review_policy_none()} · Intern (${m.flow_step_security_inherit()})`);
    expect(getChapterControlStatus(step({ output_classification_override: undefined }))).toBe(
      `${m.flow_step_review_policy_none()} · ${m.flow_step_security_inherit_summary()}`
    );
  });

  it("summarizes an enabled review and explicit classification", () => {
    expect(
      getChapterControlStatus(
        step({ output_classification_override: 3, review_policy: { mode: "edit" } }),
        null,
        [{ security_level: 3, name: "Begränsad" }]
      )
    ).toBe(`${m.flow_step_review_policy_edit()} · Begränsad`);
  });
});

describe("task and material chapter summaries", () => {
  it("uses the instruction as the task summary without exposing multiline prompt layout", () => {
    expect(
      getChapterTaskStatus(step({}), "  Strukturera innehållet\nmed beslut och uppgifter. ", "")
    ).toBe("Strukturera innehållet med beslut och uppgifter.");
  });

  it("describes the concrete previous step and extra material", () => {
    expect(
      getChapterInputStatus({
        step: step({ input_source: "previous_step" }),
        previousStep: step({ step_order: 1, user_description: "Transkribera ljud" }),
        hasKnowledge: true,
        hasAttachments: false
      })
    ).toBe("Steg 1: Transkribera ljud · Kunskap eller filer tillagda");
  });
});

describe("getTechnicalSettingsCount", () => {
  it("counts only technical contracts and raw HTTP configuration", () => {
    expect(
      getTechnicalSettingsCount(
        step({
          input_contract: { type: "object" },
          output_contract: { type: "object" },
          input_source: "http_get",
          input_config: { url: "https://example.com" }
        })
      )
    ).toBe(3);
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
      m.flow_technical_input_contract_active()
    );
  });

  it("reports custom contracts when the output contract is set", () => {
    expect(getChapterAdvancedStatus(step({ output_contract: { type: "object" } }))).toBe(
      m.flow_technical_output_contract_active()
    );
  });
});
