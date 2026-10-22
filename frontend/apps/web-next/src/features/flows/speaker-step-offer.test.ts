import { describe, expect, it } from "vitest";
import { makeKindOption, makeKindPlace, makeKindRefusal } from "./editor/testing/fixtures";
import { makeFlow, makeStep } from "./flow-fixtures";
import type { SpeakerServiceLink } from "./flow-transcription";
import { speakerStepCandidate, speakerStepOption, speakerStepUpdate } from "./speaker-step-offer";

const service: SpeakerServiceLink = {
  id: "service-1",
  name: "Talare",
  available: true,
  meets_security_classification: true,
  is_default: true
};
const wizard = {
  transcription_enabled: true,
  transcription_speaker_service: { id: "service-1" }
};
const transcribe = makeStep(1, {
  user_description: "Transkribera",
  input_type: "audio",
  output_mode: "transcribe_only"
});
const summarize = makeStep(2, { user_description: "Sammanfatta" });
const names = { step: "Granska transkript", fieldLabel: "Deltagare", fieldName: "deltagare" };
/** The speaker step as the core gives it after the transcribing step. */
const speakers = makeKindOption("speakers", {
  configuration: {
    output_mode: "speaker_mapping",
    output_type: "json",
    review_policy: { mode: "edit" },
    output_config: {
      speaker_mapping: { participants_field: null, speaker_count_field: null, infer_names: false }
    }
  }
});

describe("the speaker step shortcut", () => {
  it("is offered after the step that transcribes, when speakers are labelled", () => {
    const flow = makeFlow({ steps: [transcribe, summarize], metadata_json: { wizard } });
    expect(speakerStepCandidate(flow, [service])).toBe(transcribe);
  });

  it("is offered only where the core allows the speaker step", () => {
    expect(speakerStepOption(makeKindPlace(2, [speakers]))).toBe(speakers);
    const refused = makeKindOption("speakers", { refusals: [makeKindRefusal()] });
    expect(speakerStepOption(makeKindPlace(2, [refused]))).toBeNull();
    expect(speakerStepOption(undefined)).toBeNull();
  });

  it("is not offered without a usable service, with speakers off, or when a step names them", () => {
    const steps = [transcribe, summarize];
    expect(speakerStepCandidate(makeFlow({ steps, metadata_json: { wizard } }), [])).toBeNull();
    expect(
      speakerStepCandidate(
        makeFlow({
          steps,
          metadata_json: { wizard: { ...wizard, transcription_diarization: false } }
        }),
        [service]
      )
    ).toBeNull();
    expect(
      speakerStepCandidate(
        makeFlow({
          steps: [transcribe, makeStep(2, { output_mode: "speaker_mapping", output_type: "json" })],
          metadata_json: { wizard }
        }),
        [service]
      )
    ).toBeNull();
    expect(
      speakerStepCandidate(makeFlow({ steps: [summarize], metadata_json: { wizard } }), [service])
    ).toBeNull();
  });

  it("adds the step after it, reviewed, reading the participants from a new list field", () => {
    const flow = makeFlow({ steps: [transcribe, summarize], metadata_json: { wizard } });
    const update = speakerStepUpdate(flow, transcribe, speakers, names);
    expect(update.step_order).toEqual([
      { step_id: "step-1" },
      { new_step: 0 },
      { step_id: "step-2" }
    ]);
    expect(update.new_steps?.[0]).toMatchObject({
      name: "Granska transkript",
      configuration: {
        input_source: "previous_step",
        input_type: "text",
        output_mode: "speaker_mapping",
        output_type: "json",
        review_policy: { mode: "edit" },
        output_config: {
          speaker_mapping: {
            participants_field: "deltagare",
            speaker_count_field: null,
            infer_names: false
          }
        }
      }
    });
    expect(update.definition.metadata_json).toEqual({
      wizard,
      form_schema: {
        fields: [{ name: "deltagare", label: "Deltagare", type: "list", required: false, order: 1 }]
      }
    });
  });

  it("reads the participants from the run form's list field when it has one", () => {
    const fields = [
      { name: "datum", label: "Datum", type: "date", required: true, order: 1 },
      { name: "narvarande", label: "Närvarande", type: "list", required: false, order: 2 }
    ];
    const flow = makeFlow({
      steps: [transcribe, summarize],
      metadata_json: { wizard, form_schema: { fields } }
    });
    const update = speakerStepUpdate(flow, transcribe, speakers, names);
    expect(update.new_steps?.[0]?.configuration.output_config).toEqual({
      speaker_mapping: {
        participants_field: "narvarande",
        speaker_count_field: null,
        infer_names: false
      }
    });
    expect(update.definition).toEqual({});
  });
});
