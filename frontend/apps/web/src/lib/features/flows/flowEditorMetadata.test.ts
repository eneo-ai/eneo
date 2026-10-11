import { describe, expect, it } from "vitest";
import { transcriptionModelNotChosen, wizardReferenceId } from "./flowEditorMetadata";

const audioFromInput = [{ input_source: "flow_input", input_type: "audio", input_config: null }];
const audioUpload = [
  {
    input_source: "previous_step",
    input_type: "text",
    input_config: { runtime_input: { enabled: true, input_format: "audio" } }
  }
];

describe("wizardReferenceId", () => {
  it("reads a blank id as no choice, as the backend does", () => {
    expect(wizardReferenceId({ id: "model-1" })).toBe("model-1");
    for (const none of [undefined, null, {}, { id: null }, { id: "" }, { id: "   " }, { id: 7 }]) {
      expect(wizardReferenceId(none)).toBeNull();
    }
  });
});

describe("transcriptionModelNotChosen", () => {
  // Every way a saved draft can say that no model is chosen.
  it.each([
    { stored: "absent", wizard: {} },
    { stored: "null", wizard: { transcription_model: null } },
    { stored: "a blank id", wizard: { transcription_model: { id: "" } } },
    { stored: "a whitespace id", wizard: { transcription_model: { id: "   " } } }
  ])("is true for an audio draft whose model is stored as $stored", ({ wizard }) => {
    for (const steps of [audioFromInput, audioUpload]) {
      expect(transcriptionModelNotChosen({ wizard, transcriptionEnabled: true, steps })).toBe(true);
    }
  });

  it("is false once a model is chosen, when transcription is off, and when no step takes audio", () => {
    const chosen = { transcription_model: { id: "model-1" } };
    expect(
      transcriptionModelNotChosen({
        wizard: chosen,
        transcriptionEnabled: true,
        steps: audioFromInput
      })
    ).toBe(false);
    expect(
      transcriptionModelNotChosen({
        wizard: {},
        transcriptionEnabled: false,
        steps: audioFromInput
      })
    ).toBe(false);
    expect(transcriptionModelNotChosen({ wizard: {}, transcriptionEnabled: true, steps: [] })).toBe(
      false
    );
  });
});
