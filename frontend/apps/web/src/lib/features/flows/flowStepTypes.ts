import type { FlowStep } from "@intric/intric-js";

type InputType = FlowStep["input_type"];
type InputSource = FlowStep["input_source"];
type OutputType = FlowStep["output_type"];

export type FlowStepLike = Pick<
  FlowStep,
  "step_order" | "input_source" | "input_type" | "output_type"
>;

export type FlowStepValidationIssue = {
  code: string;
  field: "input_source" | "input_type" | "step_order";
  stepOrder: number;
  previousOutputType?: OutputType;
};

export type SelectableInputTypeOption = {
  value: InputType;
  disabled: boolean;
  legacyInvalid: boolean;
};

export type SelectableInputSourceOption = {
  value: InputSource;
  legacyInvalid: boolean;
};

const INPUT_TYPE_ORDER: InputType[] = [
  "text",
  "json",
  "document",
  "file",
  "image",
  "audio",
  "any",
];

const INPUT_SOURCE_ORDER: InputSource[] = [
  "flow_input",
  "previous_step",
  "all_previous_steps",
  "http_get",
  "http_post",
];

const ADVANCED_ONLY_INPUT_TYPES = new Set<InputType>(["file", "any"]);

const COMPATIBLE_COERCIONS: Record<OutputType, InputType[]> = {
  text: ["text", "json", "any"],
  json: ["text", "json", "any"],
  pdf: ["text", "any"],
  docx: ["text", "any"],
};

export function mapOutputToInputType(outputType?: OutputType): InputType {
  if (!outputType) return "text";
  const validInputTypes = new Set<InputType>(["text", "json", "image", "audio", "document", "file", "any"]);
  return validInputTypes.has(outputType as InputType) ? (outputType as InputType) : "text";
}

export function getValidInputTypes(
  inputSource: InputSource,
  previousOutputType?: OutputType,
): InputType[] {
  switch (inputSource) {
    case "flow_input":
      return ["text", "json", "document", "file", "audio", "any"];
    case "all_previous_steps":
      return ["text", "any"];
    case "http_get":
    case "http_post":
      return ["text", "json", "any"];
    case "previous_step":
      return previousOutputType ? [...(COMPATIBLE_COERCIONS[previousOutputType] ?? ["text", "any"])] : ["text", "any"];
    default:
      return ["text"];
  }
}

export function getValidInputSources(params: {
  steps: FlowStepLike[];
  stepOrder: number;
}): InputSource[] {
  if (params.stepOrder === 1) {
    return ["flow_input", "http_get", "http_post"];
  }
  return ["previous_step", "all_previous_steps", "http_get", "http_post"];
}

export function getSelectableInputSourceOptions(params: {
  steps: FlowStepLike[];
  stepOrder: number;
  currentInputSource?: InputSource;
}): SelectableInputSourceOption[] {
  const { steps, stepOrder, currentInputSource } = params;
  const visible = getValidInputSources({ steps, stepOrder });
  let options = INPUT_SOURCE_ORDER
    .filter((value) => visible.includes(value))
    .map((value) => ({ value, legacyInvalid: false }));

  if (currentInputSource && !options.some((option) => option.value === currentInputSource)) {
    options = [
      { value: currentInputSource, legacyInvalid: true },
      ...options,
    ];
  }

  return options;
}

function insertInCanonicalOrder(values: InputType[], value: InputType): InputType[] {
  if (values.includes(value)) return values;
  const next = [...values, value];
  return INPUT_TYPE_ORDER.filter((candidate) => next.includes(candidate));
}

export function getSelectableInputTypeOptions(params: {
  inputSource: InputSource;
  previousOutputType?: OutputType;
  currentInputType?: InputType;
  isAdvancedMode: boolean;
}): SelectableInputTypeOption[] {
  const { inputSource, previousOutputType, currentInputType, isAdvancedMode } = params;
  const valid = getValidInputTypes(inputSource, previousOutputType);
  let visible = INPUT_TYPE_ORDER.filter((value) => {
    if (value === "image") return false;
    if (!valid.includes(value)) return false;
    if (!isAdvancedMode && ADVANCED_ONLY_INPUT_TYPES.has(value)) return false;
    return true;
  });

  if (isAdvancedMode && inputSource === "flow_input") {
    visible = insertInCanonicalOrder(visible, "image");
  }

  let options = visible.map((value) => ({
    value,
    disabled: value === "image",
    legacyInvalid: false,
  }));

  if (currentInputType && !options.some((option) => option.value === currentInputType)) {
    const currentIsValid = valid.includes(currentInputType);
    if (currentIsValid) {
      const merged = insertInCanonicalOrder(
        options.map((option) => option.value),
        currentInputType,
      );
      options = merged.map((value) => ({
        value,
        disabled: value === "image",
        legacyInvalid: false,
      }));
    } else {
      options = [
        {
          value: currentInputType,
          disabled: false,
          legacyInvalid: true,
        },
        ...options,
      ];
    }
  }

  return options;
}

export function getPreferredInputType(params: {
  inputSource: InputSource;
  previousOutputType?: OutputType;
  isAdvancedMode: boolean;
}): InputType {
  const [firstOption] = getSelectableInputTypeOptions({
    ...params,
    currentInputType: undefined,
  }).filter((option) => !option.disabled);
  return firstOption?.value ?? "text";
}

export function getFlowStepValidationIssues(steps: FlowStepLike[]): FlowStepValidationIssue[] {
  if (steps.length === 0) return [];

  const issues: FlowStepValidationIssue[] = [];
  const sortedSteps = [...steps].sort((left, right) => left.step_order - right.step_order);
  const stepOrders = sortedSteps.map((step) => step.step_order);

  if (stepOrders.length !== new Set(stepOrders).size) {
    issues.push({
      code: "typed_io_duplicate_step_order",
      field: "step_order",
      stepOrder: stepOrders[0] ?? 1,
    });
    return issues;
  }

  const expectedOrders = Array.from({ length: sortedSteps.length }, (_, index) => index + 1);
  if (stepOrders.some((stepOrder, index) => stepOrder !== expectedOrders[index])) {
    issues.push({
      code: "typed_io_non_contiguous_step_order",
      field: "step_order",
      stepOrder: stepOrders.find((stepOrder, index) => stepOrder !== expectedOrders[index]) ?? 1,
    });
    return issues;
  }

  const stepByOrder = new Map(sortedSteps.map((step) => [step.step_order, step]));
  const flowInputSteps = sortedSteps.filter((step) => step.input_source === "flow_input");
  if (flowInputSteps.length > 1) {
    issues.push({
      code: "typed_io_multiple_flow_input_steps",
      field: "input_source",
      stepOrder: flowInputSteps[1].step_order,
    });
  } else if (flowInputSteps.length === 1 && flowInputSteps[0].step_order !== 1) {
    issues.push({
      code: "typed_io_flow_input_position_invalid",
      field: "input_source",
      stepOrder: flowInputSteps[0].step_order,
    });
  }

  for (const step of sortedSteps) {
    if (step.step_order === 1 && (step.input_source === "previous_step" || step.input_source === "all_previous_steps")) {
      issues.push({
        code: "typed_io_invalid_input_source_position",
        field: "input_source",
        stepOrder: step.step_order,
      });
      continue;
    }

    if (step.input_type === "image") {
      issues.push({
        code: "typed_io_unsupported_type",
        field: "input_type",
        stepOrder: step.step_order,
      });
      continue;
    }

    if (step.input_type === "document" && step.input_source !== "flow_input") {
      issues.push({
        code: "typed_io_document_source_unsupported",
        field: "input_type",
        stepOrder: step.step_order,
      });
      continue;
    }

    if (step.input_type === "audio" && step.input_source !== "flow_input") {
      issues.push({
        code: "typed_io_audio_source_unsupported",
        field: "input_type",
        stepOrder: step.step_order,
      });
      continue;
    }

    if (step.input_type === "file" && step.input_source !== "flow_input") {
      issues.push({
        code: "typed_io_file_source_unsupported",
        field: "input_type",
        stepOrder: step.step_order,
      });
      continue;
    }

    if (step.input_type === "json" && step.input_source === "all_previous_steps") {
      issues.push({
        code: "typed_io_invalid_input_source_combination",
        field: "input_type",
        stepOrder: step.step_order,
      });
      continue;
    }

    if (step.input_source === "previous_step" && step.step_order > 1) {
      const previousStep = stepByOrder.get(step.step_order - 1);
      if (!previousStep) {
        issues.push({
          code: "typed_io_missing_previous_step",
          field: "input_source",
          stepOrder: step.step_order,
        });
        continue;
      }
      const validInputTypes = getValidInputTypes("previous_step", previousStep.output_type);
      if (!validInputTypes.includes(step.input_type)) {
        issues.push({
          code: "typed_io_incompatible_type_chain",
          field: "input_type",
          stepOrder: step.step_order,
          previousOutputType: previousStep.output_type,
        });
      }
    }
  }

  return issues;
}
