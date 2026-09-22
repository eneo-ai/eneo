import { describe, expect, it } from "vitest";
import {
  getSectionProcessingEligibility,
  getTextProcessingMode,
  shouldShowReadingMode,
  updateTextProcessingMode
} from "./flowTextProcessingConfig";

const jsonStep = (input_config: Record<string, unknown> | null = null) => ({
  input_config,
  output_mode: "pass_through" as const,
  output_type: "json" as const
});

describe("flowTextProcessingConfig", () => {
  it("reads the persisted mode and ignores unknown shapes", () => {
    expect(getTextProcessingMode({ input_config: null })).toBeNull();
    expect(
      getTextProcessingMode({ input_config: { text_processing: { mode: "other" } } })
    ).toBeNull();
    expect(
      getTextProcessingMode({ input_config: { text_processing: { mode: "process_each_section" } } })
    ).toBe("process_each_section");
  });

  it("writes and clears the mode without touching sibling config", () => {
    const step = jsonStep({ runtime_input: { enabled: true } });
    const on = updateTextProcessingMode(step, "process_each_section");
    expect(on).toEqual({
      runtime_input: { enabled: true },
      text_processing: { mode: "process_each_section" }
    });
    expect(updateTextProcessingMode({ input_config: on }, null)).toEqual({
      runtime_input: { enabled: true }
    });
  });

  it("mirrors the runtime's admission rule", () => {
    expect(getSectionProcessingEligibility(jsonStep())).toEqual({ eligible: true, reason: null });
    expect(getSectionProcessingEligibility({ ...jsonStep(), output_type: "text" }).reason).toBe(
      "output"
    );
    expect(
      getSectionProcessingEligibility({ ...jsonStep(), output_mode: "http_post" }).reason
    ).toBe("output");
    expect(
      getSectionProcessingEligibility(
        jsonStep({ runtime_input: { enabled: true, execution_mode: "per_source" } })
      ).reason
    ).toBe("mapped");
    expect(getSectionProcessingEligibility(jsonStep({ item_map: { enabled: true } })).reason).toBe(
      "mapped"
    );
  });

  it("keeps the reading choice reachable while a mode is saved, even on an HTTP source", () => {
    const base = { eligible: false, isAdvancedMode: false, isHttpSource: true };
    expect(shouldShowReadingMode({ ...base, mode: "process_each_section" })).toBe(true);
    expect(shouldShowReadingMode({ ...base, mode: null })).toBe(false);
    expect(
      shouldShowReadingMode({ ...base, isHttpSource: false, eligible: true, mode: null })
    ).toBe(true);
    expect(
      shouldShowReadingMode({ ...base, isHttpSource: false, isAdvancedMode: true, mode: null })
    ).toBe(true);
  });
});
