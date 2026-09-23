import type { FlowRunContractTranscription } from "@eneo/eneo-js";
import type { NormalizedFlowFormField } from "$lib/features/flows/flowFormSchema";
import { getFlowFormFieldRuntimeKey } from "$lib/features/flows/flowFormSchema";
import type { ReusedFlowRunInput } from "$lib/features/flows/flowRunContract";

export class FlowRunLaunchInputState {
  #formValues = $state<Record<string, unknown>>({});
  #freeformText = $state("");
  #liveTextOn = $state(true);
  // The user's own speaker-label choice; null until they make one.
  #speakerLabelsChoice = $state<boolean | null>(null);

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

  get liveTextOn(): boolean {
    return this.#liveTextOn;
  }

  // The run's `speaker_labels`, or undefined when the flow leaves the run no
  // choice. Labels add waiting time after the recording, so they stay off while
  // live text is on and follow the flow's setting otherwise; the user's own
  // choice wins over both.
  speakerLabels(
    transcription: FlowRunContractTranscription | null | undefined
  ): boolean | undefined {
    if (!transcription?.speaker_labels.selectable) return undefined;
    const liveText = transcription.live.available && this.#liveTextOn;
    return this.#speakerLabelsChoice ?? (liveText ? false : transcription.speaker_labels.default);
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

  setLiveTextOn(value: boolean): void {
    this.#liveTextOn = value;
  }

  setSpeakerLabels(value: boolean): void {
    this.#speakerLabelsChoice = value;
  }

  applyReusedInput(input: ReusedFlowRunInput): void {
    this.#formValues = copyFormValues(input.formValues);
    this.#freeformText = input.freeformText;
  }

  reset(): void {
    this.#formValues = {};
    this.#freeformText = "";
    this.#liveTextOn = true;
    this.#speakerLabelsChoice = null;
  }
}

function copyFormValues(values: Readonly<Record<string, unknown>>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [key, Array.isArray(value) ? [...value] : value])
  );
}
