import { describe, expect, it } from "vitest";

import {
  buildRuntimeInputStepPatch,
  coerceRuntimeInputConfigForStep,
  getRuntimeInputConfig,
  updateRuntimeInputConfig
} from "./flowRuntimeInputConfig";

describe("flowRuntimeInputConfig", () => {
  it("returns disabled defaults when the step has no runtime input config", () => {
    expect(getRuntimeInputConfig({ input_config: null })).toEqual({
      enabled: false,
      required: false,
      max_files: null,
      input_format: "document",
      accepted_mimetypes_override: [],
      label: "",
      description: ""
    });
  });

  it("persists runtime_input under input_config", () => {
    expect(
      updateRuntimeInputConfig(
        { input_config: { timeout_seconds: 30 } },
        {
          enabled: true,
          required: true,
          max_files: 2,
          input_format: "file",
          accepted_mimetypes_override: ["application/pdf"],
          label: "Bilagor",
          description: "Ladda upp filer"
        }
      )
    ).toEqual({
      timeout_seconds: 30,
      runtime_input: {
        enabled: true,
        required: true,
        max_files: 2,
        input_format: "file",
        accepted_mimetypes_override: ["application/pdf"],
        label: "Bilagor",
        description: "Ladda upp filer"
      }
    });
  });

  it("forces audio runtime inputs for transcribe_only steps", () => {
    expect(
      coerceRuntimeInputConfigForStep(
        {
          output_mode: "transcribe_only",
          input_type: "audio"
        },
        {
          enabled: true,
          required: false,
          max_files: null,
          input_format: "document",
          accepted_mimetypes_override: [],
          label: "",
          description: ""
        }
      ).input_format
    ).toBe("audio");
  });

  it("drops incompatible explicit question bindings when runtime input is enabled", () => {
    expect(
      buildRuntimeInputStepPatch(
        {
          input_type: "text",
          output_mode: "pass_through",
          input_config: null,
          input_bindings: {
            question: "{{step_1.output.text}}",
            extra: "{{case_id}}"
          }
        },
        {
          enabled: true,
          required: false,
          max_files: null,
          input_format: "document",
          accepted_mimetypes_override: [],
          label: "",
          description: ""
        }
      )
    ).toEqual({
      input_config: {
        runtime_input: {
          enabled: true,
          required: false,
          input_format: "document"
        }
      },
      input_bindings: {
        extra: "{{case_id}}"
      }
    });
  });

  it("keeps explicit question bindings that already consume step_input", () => {
    expect(
      buildRuntimeInputStepPatch(
        {
          input_type: "text",
          output_mode: "pass_through",
          input_config: null,
          input_bindings: {
            question: "Sammanfatta {{step_input.text}}"
          }
        },
        {
          enabled: true,
          required: true,
          max_files: 2,
          input_format: "document",
          accepted_mimetypes_override: [],
          label: "Bilagor",
          description: "Ladda upp filer"
        }
      ).input_bindings
    ).toEqual({
      question: "Sammanfatta {{step_input.text}}"
    });
  });
});
