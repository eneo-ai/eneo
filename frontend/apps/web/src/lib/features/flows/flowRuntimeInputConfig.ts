import type { FlowStep } from "@intric/intric-js";

export type FlowRuntimeInputFormat = "document" | "audio" | "file";

export type FlowRuntimeInputConfigValue = {
  enabled: boolean;
  required: boolean;
  max_files: number | null;
  input_format: FlowRuntimeInputFormat;
  accepted_mimetypes_override: string[];
  label: string;
  description: string;
};

type RuntimeInputBindings = Record<string, unknown> | null;
type RuntimeInputStepLike = Pick<
  FlowStep,
  "input_bindings" | "input_config" | "input_type" | "output_mode"
>;

const DEFAULT_RUNTIME_INPUT_CONFIG: FlowRuntimeInputConfigValue = {
  enabled: false,
  required: false,
  max_files: null,
  input_format: "document",
  accepted_mimetypes_override: [],
  label: "",
  description: ""
};

function asObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function sanitizeString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function sanitizeStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter((item) => item.length > 0);
}

function sanitizeMaxFiles(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (value <= 0) return null;
  return Math.floor(value);
}

export function coerceRuntimeInputConfigForStep(
  step: Pick<FlowStep, "input_type" | "output_mode">,
  config: FlowRuntimeInputConfigValue
): FlowRuntimeInputConfigValue {
  if (step.output_mode === "transcribe_only" || step.input_type === "audio") {
    return { ...config, input_format: "audio" };
  }
  return config;
}

export function getRuntimeInputConfig(
  step: Pick<FlowStep, "input_config" | "input_type" | "output_mode">
): FlowRuntimeInputConfigValue {
  const inputConfig = asObject(step.input_config);
  const runtimeInputRaw = inputConfig?.runtime_input;

  if (runtimeInputRaw === true) {
    return coerceRuntimeInputConfigForStep(step, {
      ...DEFAULT_RUNTIME_INPUT_CONFIG,
      enabled: true
    });
  }

  const runtimeInput = asObject(runtimeInputRaw);
  if (!runtimeInput) {
    return { ...DEFAULT_RUNTIME_INPUT_CONFIG };
  }

  return coerceRuntimeInputConfigForStep(step, {
    enabled: Boolean(runtimeInput.enabled),
    required: Boolean(runtimeInput.required),
    max_files: sanitizeMaxFiles(runtimeInput.max_files),
    input_format:
      runtimeInput.input_format === "audio" || runtimeInput.input_format === "file"
        ? runtimeInput.input_format
        : "document",
    accepted_mimetypes_override: sanitizeStringList(runtimeInput.accepted_mimetypes_override),
    label: sanitizeString(runtimeInput.label),
    description: sanitizeString(runtimeInput.description)
  });
}

function serializeRuntimeInputConfig(
  config: FlowRuntimeInputConfigValue
): Record<string, unknown> | false {
  if (!config.enabled) {
    return false;
  }

  const payload: Record<string, unknown> = {
    enabled: true,
    required: config.required,
    input_format: config.input_format
  };

  if (config.max_files !== null) {
    payload.max_files = config.max_files;
  }
  if (config.accepted_mimetypes_override.length > 0) {
    payload.accepted_mimetypes_override = config.accepted_mimetypes_override;
  }
  if (config.label.trim().length > 0) {
    payload.label = config.label.trim();
  }
  if (config.description.trim().length > 0) {
    payload.description = config.description.trim();
  }

  return payload;
}

export function updateRuntimeInputConfig(
  step: Pick<FlowStep, "input_config" | "input_type" | "output_mode">,
  config: FlowRuntimeInputConfigValue
): Record<string, unknown> {
  const nextConfig = coerceRuntimeInputConfigForStep(step, config);
  const inputConfig = { ...(asObject(step.input_config) ?? {}) };
  inputConfig.runtime_input = serializeRuntimeInputConfig(nextConfig);
  return inputConfig;
}

function sanitizeRuntimeInputBindings(
  bindings: unknown,
  runtimeInputEnabled: boolean
): RuntimeInputBindings {
  if (!runtimeInputEnabled || !bindings || typeof bindings !== "object" || Array.isArray(bindings)) {
    return (bindings as RuntimeInputBindings | undefined) ?? null;
  }

  const nextBindings = { ...(bindings as Record<string, unknown>) };
  const questionBinding = nextBindings.question;
  if (
    typeof questionBinding === "string" &&
    questionBinding.trim().length > 0 &&
    !questionBinding.includes("step_input.")
  ) {
    delete nextBindings.question;
  }

  return Object.keys(nextBindings).length > 0 ? nextBindings : null;
}

export function buildRuntimeInputStepPatch(
  step: RuntimeInputStepLike,
  config: FlowRuntimeInputConfigValue
): Pick<FlowStep, "input_bindings" | "input_config"> {
  const nextConfig = coerceRuntimeInputConfigForStep(step, config);
  return {
    input_config: updateRuntimeInputConfig(step, nextConfig),
    input_bindings: sanitizeRuntimeInputBindings(step.input_bindings, nextConfig.enabled)
  };
}
