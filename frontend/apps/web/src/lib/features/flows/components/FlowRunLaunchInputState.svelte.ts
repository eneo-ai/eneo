import type { FlowRunContractTranscription } from "@eneo/eneo-js";
import type { NormalizedFlowFormField } from "$lib/features/flows/flowFormSchema";
import { getFlowFormFieldRuntimeKey } from "$lib/features/flows/flowFormSchema";
import type { ReusedFlowRunInput } from "$lib/features/flows/flowRunContract";

export class FlowRunLaunchInputState {
  #formValues = $state<Record<string, unknown>>({});
  #freeformText = $state("");
  #liveTextOn = $state(true);
  // Whether a recording's live text has streamed in this dialog.
  #liveSessionStarted = $state(false);
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
  // choice. The user's own choice wins. Otherwise labels are off once live text
  // has streamed, since they add waiting time after the recording, and a run
  // that only uploads keeps the flow's own setting.
  speakerLabels(
    transcription: FlowRunContractTranscription | null | undefined
  ): boolean | undefined {
    if (!transcription?.speaker_labels.selectable) return undefined;
    return (
      this.#speakerLabelsChoice ??
      (this.#liveSessionStarted ? false : transcription.speaker_labels.default)
    );
  }

  // Whether streaming, rather than the user or the flow, turned labels off.
  speakerLabelsOffForStreaming(
    transcription: FlowRunContractTranscription | null | undefined
  ): boolean {
    return (
      this.#speakerLabelsChoice === null &&
      this.#liveSessionStarted &&
      transcription?.speaker_labels.selectable === true &&
      transcription.speaker_labels.default
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

  setLiveTextOn(value: boolean): void {
    this.#liveTextOn = value;
  }

  markLiveSessionStarted(): void {
    this.#liveSessionStarted = true;
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
    this.#liveSessionStarted = false;
    this.#speakerLabelsChoice = null;
  }
}

function copyFormValues(values: Readonly<Record<string, unknown>>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(values).map(([key, value]) => [key, Array.isArray(value) ? [...value] : value])
  );
}
