import type { NormalizedFlowFormField } from "$lib/features/flows/flowFormSchema";
import { getFlowFormFieldRuntimeKey } from "$lib/features/flows/flowFormSchema";
import type { ReusedFlowRunInput } from "$lib/features/flows/flowRunContract";

export class FlowRunLaunchInputState {
  #formValues = $state<Record<string, unknown>>({});
  #freeformText = $state("");

  get formValuesSnapshot(): Readonly<Record<string, unknown>> {
    return copyFormValues(this.#formValues);
  }

  get freeformText(): string {
    return this.#freeformText;
  }

  get hasDirtyInput(): boolean {
    return (
      Object.values(this.#formValues).some(
        (value) => value !== null && value !== undefined && String(value).trim() !== ""
      ) || this.#freeformText.trim().length > 0
    );
  }

  setFreeformText(value: string): void {
    this.#freeformText = value;
  }

  setFieldValue(field: NormalizedFlowFormField, value: unknown): void {
    this.#formValues = {
      ...this.#formValues,
      [getFlowFormFieldRuntimeKey(field.name)]: value
    };
  }

  applyReusedInput(input: ReusedFlowRunInput): void {
    this.#formValues = copyFormValues(input.formValues);
    this.#freeformText = input.freeformText;
  }

  reset(): void {
    this.#formValues = {};
    this.#freeformText = "";
  }
}

function copyFormValues(values: Readonly<Record<string, unknown>>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [key, Array.isArray(value) ? [...value] : value])
  );
}
