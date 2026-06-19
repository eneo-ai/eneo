import type { FlowStep } from "@intric/intric-js";

import { sanitizeStepCitationMode } from "./flowCitationMode";
import { getSelectableInputTypeOptions, type SelectableInputTypeOption } from "./flowStepTypes";
import { getRecommendedDisplayedInputType } from "./flowStepPresentation";
import {
  FILE_BASED_INPUT_TYPES,
  buildRuntimeInputStepPatch,
  isDefaultRuntimeConfig,
  type FlowRuntimeInputConfigValue,
  type FlowRuntimeInputFormat
} from "./flowRuntimeInputConfig";
import {
  createTemplateFillDraftConfig,
  type getTemplateFillOutputConfig
} from "./templateFillConfig";
import { sanitizeFlowStepReviewPolicy } from "./flowStepReviewPolicy";
import { createDefaultHttpConfig } from "./components/http/httpConfigDefaults";
import { parseHttpAuthoredConfig, type HttpMethod } from "./components/http/httpConfigTypes";

type StepInputSource = FlowStep["input_source"];
type StepInputType = FlowStep["input_type"];
type StepOutputMode = FlowStep["output_mode"];
type StepOutputType = FlowStep["output_type"];

export type InputSourceChangeResult = {
  step: FlowStep;
  inputTypeAdjusted: boolean;
};

export type InputTypeChangeResult = {
  step: FlowStep;
  inputSourceAdjusted: boolean;
};

export function applyInputSourceChange({
  step,
  nextSource,
  previousOutputType,
  runtimeInputConfig,
  isAdvancedMode
}: {
  step: FlowStep;
  nextSource: StepInputSource;
  previousOutputType: StepOutputType | undefined;
  runtimeInputConfig: FlowRuntimeInputConfigValue;
  isAdvancedMode: boolean;
}): InputSourceChangeResult {
  const httpSourceSelected = nextSource === "http_get" || nextSource === "http_post";
  const nextInputTypeOptions = getSelectableInputTypeOptions({
    inputSource: nextSource,
    previousOutputType,
    currentInputType: step.input_type,
    isAdvancedMode
  });
  const nextInputConfig = httpSourceSelected
    ? withHttpInputSourceDefaults(step.input_config, nextSource === "http_get" ? "GET" : "POST")
    : (step.input_config ?? null);
  const nextInputType = keepOrRecommendInputType({
    currentInputType: step.input_type,
    options: nextInputTypeOptions,
    inputSource: nextSource,
    previousOutputType
  });

  let finalInputConfig = nextInputConfig;
  let finalBindings = step.input_bindings;

  if (nextInputType !== step.input_type) {
    const wasFileBased = FILE_BASED_INPUT_TYPES.has(step.input_type);
    const nowFileBased = FILE_BASED_INPUT_TYPES.has(nextInputType);
    if (nowFileBased && !runtimeInputConfig.enabled) {
      const patch = buildRuntimeInputStepPatch(
        {
          ...step,
          input_config: nextInputConfig,
          input_type: nextInputType,
          output_mode: step.output_mode
        },
        {
          ...runtimeInputConfig,
          enabled: true,
          required: true,
          input_format: nextInputType as FlowRuntimeInputFormat
        }
      );
      finalInputConfig = patch.input_config ?? null;
      finalBindings = patch.input_bindings ?? null;
    } else if (
      !nowFileBased &&
      wasFileBased &&
      runtimeInputConfig.enabled &&
      isDefaultRuntimeConfig(runtimeInputConfig)
    ) {
      const patch = buildRuntimeInputStepPatch(
        {
          ...step,
          input_config: nextInputConfig,
          input_type: nextInputType,
          output_mode: step.output_mode
        },
        { ...runtimeInputConfig, enabled: false }
      );
      finalInputConfig = patch.input_config ?? null;
      finalBindings = patch.input_bindings ?? null;
    }
  }

  return {
    step: {
      ...step,
      input_source: nextSource,
      input_type: nextInputType,
      input_config: finalInputConfig,
      input_bindings: finalBindings ?? null
    },
    inputTypeAdjusted: nextInputType !== step.input_type
  };
}

export function applyInputTypeChange({
  step,
  nextType,
  runtimeInputConfig
}: {
  step: FlowStep;
  nextType: StepInputType;
  runtimeInputConfig: FlowRuntimeInputConfigValue;
}): InputTypeChangeResult {
  const isAudioInput = nextType === "audio";
  const nextOutputMode: StepOutputMode = isAudioInput
    ? "transcribe_only"
    : step.output_mode === "transcribe_only"
      ? "pass_through"
      : step.output_mode;
  const nextOutputType: StepOutputType = isAudioInput ? "text" : step.output_type;
  const nextInputSource: StepInputSource =
    (nextType === "document" || nextType === "audio" || nextType === "file") &&
    step.input_source !== "flow_input"
      ? "flow_input"
      : step.input_source;

  const wasFileBased = FILE_BASED_INPUT_TYPES.has(step.input_type);
  const nowFileBased = FILE_BASED_INPUT_TYPES.has(nextType);
  let runtimePatch: Partial<FlowStep> = {};
  if (nowFileBased && !runtimeInputConfig.enabled) {
    runtimePatch = buildRuntimeInputStepPatch(
      { ...step, input_type: nextType, output_mode: nextOutputMode },
      {
        ...runtimeInputConfig,
        enabled: true,
        required: true,
        input_format: nextType as FlowRuntimeInputFormat
      }
    );
  } else if (
    !nowFileBased &&
    wasFileBased &&
    runtimeInputConfig.enabled &&
    isDefaultRuntimeConfig(runtimeInputConfig)
  ) {
    runtimePatch = buildRuntimeInputStepPatch(
      { ...step, input_type: nextType, output_mode: nextOutputMode },
      { ...runtimeInputConfig, enabled: false }
    );
  }

  return {
    step: sanitizeStepCitationMode({
      ...step,
      ...runtimePatch,
      input_type: nextType,
      input_source: nextInputSource,
      output_mode: nextOutputMode,
      output_type: nextOutputType
    }),
    inputSourceAdjusted: nextInputSource !== step.input_source
  };
}

export function applyOutputModeChange({
  step,
  nextMode,
  runtimeInputConfig,
  templateFillConfig
}: {
  step: FlowStep;
  nextMode: StepOutputMode;
  runtimeInputConfig: FlowRuntimeInputConfigValue;
  templateFillConfig: ReturnType<typeof getTemplateFillOutputConfig>;
}): FlowStep {
  if (nextMode === "transcribe_only") {
    const audioPatch = !runtimeInputConfig.enabled
      ? buildRuntimeInputStepPatch(
          { ...step, input_type: "audio", output_mode: "transcribe_only" },
          { ...runtimeInputConfig, enabled: true, required: true, input_format: "audio" }
        )
      : {};
    return sanitizeFlowStepReviewPolicy(
      sanitizeStepCitationMode({
        ...step,
        ...audioPatch,
        input_type: "audio",
        input_source: "flow_input",
        output_mode: "transcribe_only",
        output_type: "text"
      })
    );
  }

  if (nextMode === "template_fill") {
    return sanitizeFlowStepReviewPolicy(
      sanitizeStepCitationMode({
        ...step,
        output_mode: "template_fill",
        output_type: "docx",
        output_contract: null,
        output_config: createTemplateFillDraftConfig(templateFillConfig)
      })
    );
  }

  return sanitizeFlowStepReviewPolicy(sanitizeStepCitationMode({ ...step, output_mode: nextMode }));
}

export function applyOutputTypeChange({
  step,
  nextType
}: {
  step: FlowStep;
  nextType: StepOutputType;
}): FlowStep {
  const nextMode =
    step.output_mode === "template_fill" && nextType !== "docx" ? "pass_through" : step.output_mode;

  return sanitizeFlowStepReviewPolicy(
    sanitizeStepCitationMode({ ...step, output_type: nextType, output_mode: nextMode })
  );
}

function withHttpInputSourceDefaults(
  inputConfig: FlowStep["input_config"],
  method: HttpMethod
): Record<string, unknown> {
  const currentConfig = isInputConfigRecord(inputConfig) ? inputConfig : {};
  return {
    ...currentConfig,
    ...parseHttpAuthoredConfig(currentConfig, createDefaultHttpConfig("input", method))
  };
}

function isInputConfigRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function keepOrRecommendInputType({
  currentInputType,
  options,
  inputSource,
  previousOutputType
}: {
  currentInputType: StepInputType;
  options: SelectableInputTypeOption[];
  inputSource: StepInputSource;
  previousOutputType: StepOutputType | undefined;
}): StepInputType {
  if (
    options.some(
      (option) => option.value === currentInputType && !option.disabled && !option.legacyInvalid
    )
  ) {
    return currentInputType;
  }

  return getRecommendedDisplayedInputType({
    options,
    inputSource,
    previousOutputType
  });
}
