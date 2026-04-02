import { describe, expect, test } from "vitest";
import type { FlowStep } from "@intric/intric-js";
import {
  hasAdvancedSettingsActive,
  getTemplateAssetStatusClass,
  getTemplateRowStatusClass,
  getTemplateReadinessPillClass,
  parseMimeOverrideDraft,
  getMimePresetsForFormat,
  MIME_PRESETS_DOCUMENT,
  MIME_PRESETS_AUDIO,
  getTemplateAssetStatusLabel
} from "./flowStepEditHelpers";

function makeStep(overrides: Partial<FlowStep> = {}): FlowStep {
  return {
    id: "step-1",
    step_order: 1,
    user_description: "Test step",
    input_source: "flow_input",
    input_type: "text",
    output_type: "text",
    output_mode: "pass_through",
    mcp_policy: "inherit",
    input_contract: null,
    output_contract: null,
    input_config: null,
    output_config: null,
    input_bindings: null,
    output_classification_override: null,
    assistant_id: null,
    ...overrides
  } as FlowStep;
}

// ---------------------------------------------------------------------------
// hasAdvancedSettingsActive
// ---------------------------------------------------------------------------

describe("hasAdvancedSettingsActive", () => {
  test("returns false for a vanilla step with no overrides", () => {
    expect(hasAdvancedSettingsActive(makeStep(), false)).toBe(false);
  });

  test("returns true when output_mode is template_fill", () => {
    expect(hasAdvancedSettingsActive(makeStep({ output_mode: "template_fill" }), false)).toBe(true);
  });

  test("returns true when input_type is any", () => {
    expect(hasAdvancedSettingsActive(makeStep({ input_type: "any" }), false)).toBe(true);
  });

  test("returns true when input_type is file", () => {
    expect(hasAdvancedSettingsActive(makeStep({ input_type: "file" }), false)).toBe(true);
  });

  test("returns true when mcp_policy is restricted", () => {
    expect(hasAdvancedSettingsActive(makeStep({ mcp_policy: "restricted" }), false)).toBe(true);
  });

  test("returns true when input_contract is set", () => {
    expect(hasAdvancedSettingsActive(makeStep({ input_contract: { type: "object" } }), false)).toBe(
      true
    );
  });

  test("returns true when output_contract is set", () => {
    expect(
      hasAdvancedSettingsActive(makeStep({ output_contract: { type: "object" } }), false)
    ).toBe(true);
  });

  test("returns false when output_config only contains citation mode", () => {
    expect(
      hasAdvancedSettingsActive(
        makeStep({ output_config: { citation_mode: "inline_inref_sidecar" } }),
        false
      )
    ).toBe(false);
  });

  test("returns true when hasInputTemplateOverride is true", () => {
    expect(hasAdvancedSettingsActive(makeStep(), true)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// parseMimeOverrideDraft
// ---------------------------------------------------------------------------

describe("parseMimeOverrideDraft", () => {
  test("splits comma-separated values and trims whitespace", () => {
    expect(parseMimeOverrideDraft("text/csv , application/pdf")).toEqual([
      "text/csv",
      "application/pdf"
    ]);
  });

  test("filters out empty strings", () => {
    expect(parseMimeOverrideDraft("text/csv,,")).toEqual(["text/csv"]);
  });

  test("returns empty array for empty input", () => {
    expect(parseMimeOverrideDraft("")).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// getMimePresetsForFormat
// ---------------------------------------------------------------------------

describe("getMimePresetsForFormat", () => {
  test("returns audio presets for audio format", () => {
    expect(getMimePresetsForFormat("audio")).toBe(MIME_PRESETS_AUDIO);
  });

  test("returns document presets for document format", () => {
    expect(getMimePresetsForFormat("document")).toBe(MIME_PRESETS_DOCUMENT);
  });

  test("returns document presets for any other format", () => {
    expect(getMimePresetsForFormat("file")).toBe(MIME_PRESETS_DOCUMENT);
  });
});

// ---------------------------------------------------------------------------
// getTemplateAssetStatusLabel
// ---------------------------------------------------------------------------

describe("getTemplateAssetStatusLabel", () => {
  test("maps ready", () => {
    expect(getTemplateAssetStatusLabel("ready")).toBe("Ready");
  });

  test("maps needs_action", () => {
    expect(getTemplateAssetStatusLabel("needs_action")).toBe("Needs action");
  });

  test("maps read_only", () => {
    expect(getTemplateAssetStatusLabel("read_only")).toBe("Read-only");
  });

  test("defaults to Unavailable for unknown", () => {
    expect(getTemplateAssetStatusLabel(null)).toBe("Unavailable");
    expect(getTemplateAssetStatusLabel(undefined)).toBe("Unavailable");
  });
});

// ---------------------------------------------------------------------------
// CSS class helpers
// ---------------------------------------------------------------------------

describe("getTemplateAssetStatusClass", () => {
  test("returns positive class for ready", () => {
    expect(getTemplateAssetStatusClass("ready")).toContain("positive");
  });

  test("returns accent class for read_only", () => {
    expect(getTemplateAssetStatusClass("read_only")).toContain("accent");
  });

  test("returns warning class for needs_action", () => {
    expect(getTemplateAssetStatusClass("needs_action")).toContain("warning");
  });

  test("returns negative class for unknown", () => {
    expect(getTemplateAssetStatusClass(null)).toContain("negative");
  });
});

describe("getTemplateRowStatusClass", () => {
  test("returns positive for matched", () => {
    expect(getTemplateRowStatusClass("matched")).toContain("positive");
  });

  test("returns warning for missing", () => {
    expect(getTemplateRowStatusClass("missing")).toContain("warning");
  });

  test("returns negative for invalid", () => {
    expect(getTemplateRowStatusClass("invalid")).toContain("negative");
  });

  test("returns negative for orphaned", () => {
    expect(getTemplateRowStatusClass("orphaned")).toContain("negative");
  });
});

describe("getTemplateReadinessPillClass", () => {
  test("returns dimmer class when total is 0", () => {
    expect(getTemplateReadinessPillClass({ total: 0, matched: 0, incomplete: false })).toContain(
      "hover-dimmer"
    );
  });

  test("returns warning class when incomplete", () => {
    expect(getTemplateReadinessPillClass({ total: 3, matched: 1, incomplete: true })).toContain(
      "warning"
    );
  });

  test("returns positive class when complete", () => {
    expect(getTemplateReadinessPillClass({ total: 3, matched: 3, incomplete: false })).toContain(
      "positive"
    );
  });
});
