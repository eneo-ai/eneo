import type { FlowRunContractTemplateReadiness, FlowRunStepInputs } from "@intric/intric-js";
import {
  getFlowFormFieldRuntimeKey,
  type NormalizedFlowFormField
} from "$lib/features/flows/flowFormSchema";

type FileLike = { id: string };

type FlowRunIntentParams = {
  publishedFlowVersion: number;
  inputPayloadJson: Record<string, unknown>;
  stepInputs?: FlowRunStepInputs;
};

type FlowRunInputModeParams = {
  formFields: NormalizedFlowFormField[];
  hasFormFields: boolean;
  showFreeformTextInput: boolean;
};

type BuildFlowRunInputPayloadParams = FlowRunInputModeParams & {
  formValues: Readonly<Record<string, unknown>>;
  freeformText: string;
};

type ComputeReusedFlowRunInputParams = FlowRunInputModeParams & {
  currentFormValues: Readonly<Record<string, unknown>>;
  currentFreeformText: string;
  lastInputPayload: Record<string, unknown> | null;
};

export type ReusedFlowRunInput = {
  formValues: Record<string, unknown>;
  freeformText: string;
};

export function getBlockingTemplateReadinessItems(
  readinessItems: FlowRunContractTemplateReadiness[]
): FlowRunContractTemplateReadiness[] {
  return readinessItems.filter(
    (item) => item.status === "needs_action" || item.status === "unavailable"
  );
}

export function hasBlockingTemplateReadiness(
  readinessItems: FlowRunContractTemplateReadiness[]
): boolean {
  return getBlockingTemplateReadinessItems(readinessItems).length > 0;
}

export function buildStepInputsPayload(
  filesByStepId: Record<string, FileLike[]>
): FlowRunStepInputs | undefined {
  const payloadEntries = Object.entries(filesByStepId)
    .map(([stepId, files]) => [stepId, files.map((file) => file.id).filter(Boolean)] as const)
    .filter(([, fileIds]) => fileIds.length > 0)
    .map(([stepId, fileIds]) => [stepId, { file_ids: fileIds }] as const);

  if (payloadEntries.length === 0) {
    return undefined;
  }

  return Object.fromEntries(payloadEntries);
}

export function buildFlowRunIntent({
  publishedFlowVersion,
  inputPayloadJson,
  stepInputs
}: FlowRunIntentParams): {
  expected_flow_version: number;
  input_payload_json: Record<string, unknown>;
  step_inputs?: FlowRunStepInputs;
} {
  return {
    expected_flow_version: publishedFlowVersion,
    input_payload_json: inputPayloadJson,
    ...(stepInputs ? { step_inputs: stepInputs } : {})
  };
}

export function readFlowRunFieldValue(
  formValues: Readonly<Record<string, unknown>>,
  field: NormalizedFlowFormField
): string {
  const value = formValues[getFlowFormFieldRuntimeKey(field.name)];
  if (Array.isArray(value)) return "";
  if (value === null || value === undefined) return "";
  return String(value);
}

export function readFlowRunFieldMultiValue(
  formValues: Readonly<Record<string, unknown>>,
  field: NormalizedFlowFormField
): string[] {
  const value = formValues[getFlowFormFieldRuntimeKey(field.name)];
  if (Array.isArray(value)) return value.map((item) => String(item));
  if (typeof value === "string" && value.trim().length > 0) {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
  }
  return [];
}

export function getMissingFlowRunRequiredFields(
  formValues: Readonly<Record<string, unknown>>,
  formFields: NormalizedFlowFormField[]
): NormalizedFlowFormField[] {
  return formFields.filter((field) => {
    if (!field.required) return false;
    if (field.type === "multiselect") {
      return readFlowRunFieldMultiValue(formValues, field).length === 0;
    }
    return readFlowRunFieldValue(formValues, field).trim().length === 0;
  });
}

export function getFlowRunReviewFieldValue(
  formValues: Readonly<Record<string, unknown>>,
  field: NormalizedFlowFormField
): string {
  if (field.type === "multiselect") {
    return readFlowRunFieldMultiValue(formValues, field).join(", ");
  }
  return readFlowRunFieldValue(formValues, field).trim();
}

export function computeReusedFlowRunInput({
  currentFormValues,
  currentFreeformText,
  lastInputPayload,
  formFields,
  hasFormFields,
  showFreeformTextInput
}: ComputeReusedFlowRunInputParams): ReusedFlowRunInput {
  const formValues: Record<string, unknown> = { ...currentFormValues };
  let freeformText = currentFreeformText;

  if (!lastInputPayload) {
    return { formValues, freeformText };
  }

  if (hasFormFields) {
    for (const field of formFields) {
      const key = getFlowFormFieldRuntimeKey(field.name);
      const previous = lastInputPayload[key];
      if (field.type === "multiselect") {
        formValues[key] = Array.isArray(previous)
          ? previous.map((item) => String(item))
          : typeof previous === "string"
            ? previous
                .split(",")
                .map((item) => item.trim())
                .filter((item) => item.length > 0)
            : [];
      } else if (previous !== undefined) {
        formValues[key] = previous;
      } else {
        formValues[key] = "";
      }
    }
  } else if (showFreeformTextInput) {
    freeformText = String(lastInputPayload.text ?? JSON.stringify(lastInputPayload));
  }

  return { formValues, freeformText };
}

export function buildFlowRunInputPayload({
  formValues,
  freeformText,
  formFields,
  hasFormFields,
  showFreeformTextInput
}: BuildFlowRunInputPayloadParams): Record<string, unknown> {
  if (hasFormFields) {
    const payload: Record<string, unknown> = {};
    for (const field of formFields) {
      const key = getFlowFormFieldRuntimeKey(field.name);
      if (field.type === "multiselect") {
        payload[key] = readFlowRunFieldMultiValue(formValues, field);
      } else if (field.type === "number") {
        const raw = readFlowRunFieldValue(formValues, field).trim();
        payload[key] = raw.length > 0 ? Number(raw) : raw;
      } else {
        payload[key] = readFlowRunFieldValue(formValues, field);
      }
    }
    return payload;
  }

  if (showFreeformTextInput) {
    return { text: freeformText };
  }

  return {};
}
