import { describe, expect, test } from "vitest";
import type { FlowStep } from "@intric/intric-js";

import {
  FLOW_CITATION_MODE_INLINE_INREF_SIDECAR,
  FLOW_CITATION_MODE_OFF,
  hasAdvancedOutputConfig,
  preserveFlowCitationMode,
  resolveFlowCitationMode,
  sanitizeStepCitationMode,
  setFlowCitationMode,
  supportsFlowCitationMode
} from "./flowCitationMode";

function makeStep(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "step-1",
    assistant_id: "assistant-1",
    step_order: 1,
    user_description: "Step",
    input_source: "flow_input",
    input_type: "text",
    output_mode: "pass_through",
    output_type: "text",
    mcp_policy: "inherit",
    input_bindings: null,
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    ...overrides
  } as FlowStep;
}

describe("flow citation mode helpers", () => {
  test("defaults to off for missing or unknown output config", () => {
    expect(resolveFlowCitationMode(null)).toBe(FLOW_CITATION_MODE_OFF);
    expect(resolveFlowCitationMode({ citation_mode: "unknown" })).toBe(FLOW_CITATION_MODE_OFF);
  });

  test("reads the inline citation mode when configured", () => {
    expect(
      resolveFlowCitationMode({ citation_mode: FLOW_CITATION_MODE_INLINE_INREF_SIDECAR })
    ).toBe(FLOW_CITATION_MODE_INLINE_INREF_SIDECAR);
  });

  test("only supports citation mode for non-template, non-transcribe text steps", () => {
    expect(supportsFlowCitationMode(makeStep())).toBe(true);
    expect(supportsFlowCitationMode(makeStep({ output_mode: "http_post" }))).toBe(true);
    expect(supportsFlowCitationMode(makeStep({ output_type: "json" }))).toBe(false);
    expect(supportsFlowCitationMode(makeStep({ output_mode: "template_fill" }))).toBe(false);
    expect(supportsFlowCitationMode(makeStep({ output_mode: "transcribe_only" }))).toBe(false);
  });

  test("adds and removes citation mode without clobbering other output config fields", () => {
    expect(setFlowCitationMode(null, FLOW_CITATION_MODE_INLINE_INREF_SIDECAR)).toEqual({
      citation_mode: FLOW_CITATION_MODE_INLINE_INREF_SIDECAR
    });

    expect(
      setFlowCitationMode(
        { url: "https://example.com", citation_mode: FLOW_CITATION_MODE_INLINE_INREF_SIDECAR },
        FLOW_CITATION_MODE_OFF
      )
    ).toEqual({
      url: "https://example.com"
    });

    expect(
      setFlowCitationMode(
        { citation_mode: FLOW_CITATION_MODE_INLINE_INREF_SIDECAR },
        FLOW_CITATION_MODE_OFF
      )
    ).toBeNull();
  });

  test("preserves citation mode when replacing http-style output config", () => {
    expect(
      preserveFlowCitationMode(
        { url: "https://example.com", auth: { mode: "none" } },
        { citation_mode: FLOW_CITATION_MODE_INLINE_INREF_SIDECAR }
      )
    ).toEqual({
      url: "https://example.com",
      auth: { mode: "none" },
      citation_mode: FLOW_CITATION_MODE_INLINE_INREF_SIDECAR
    });
  });

  test("drops citation mode automatically when a step no longer supports it", () => {
    const sanitized = sanitizeStepCitationMode(
      makeStep({
        output_mode: "template_fill",
        output_type: "docx",
        output_config: { citation_mode: FLOW_CITATION_MODE_INLINE_INREF_SIDECAR }
      })
    );

    expect(sanitized.output_config).toBeNull();
  });

  test("treats citation-only output config as non-advanced", () => {
    expect(
      hasAdvancedOutputConfig(
        makeStep({
          output_config: { citation_mode: FLOW_CITATION_MODE_INLINE_INREF_SIDECAR }
        })
      )
    ).toBe(false);

    expect(
      hasAdvancedOutputConfig(
        makeStep({
          output_mode: "http_post",
          output_config: {
            url: "https://example.com",
            citation_mode: FLOW_CITATION_MODE_INLINE_INREF_SIDECAR
          }
        })
      )
    ).toBe(true);
  });
});
