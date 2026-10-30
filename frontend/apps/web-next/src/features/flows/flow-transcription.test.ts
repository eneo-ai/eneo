import { describe, expect, it } from "vitest";
import { makeStep } from "./flow-fixtures";
import {
  flowTakesAudio,
  metadataWithTranscription,
  speakerServiceState,
  transcriptionModelMissing,
  transcriptionSettingsOf,
  withSpeakerService,
  type SpeakerServiceLink
} from "./flow-transcription";

const service = (overrides: Partial<SpeakerServiceLink> = {}): SpeakerServiceLink => ({
  id: "svc-1",
  name: "Ordtjänst",
  available: true,
  meets_security_classification: true,
  is_default: false,
  ...overrides
});

const audioStep = makeStep(1, { input_type: "audio", output_mode: "transcribe_only" });

describe("transcriptionSettingsOf", () => {
  it("reads the defaults the core reads for a flow that states nothing", () => {
    expect(transcriptionSettingsOf(null)).toEqual({
      enabled: false,
      modelId: null,
      language: "sv",
      speakerLabels: true,
      speakerService: { kind: "unset" },
      maxSpeakers: null
    });
  });

  it("tells a chosen none apart from no choice, and a blank id from a model", () => {
    const settings = transcriptionSettingsOf({
      wizard: {
        transcription_enabled: true,
        transcription_model: { id: " " },
        transcription_language: "EN",
        transcription_diarization: false,
        transcription_speaker_service: null,
        transcription_max_speakers: 0
      }
    });
    expect(settings).toMatchObject({
      enabled: true,
      modelId: null,
      language: "en",
      speakerLabels: false,
      speakerService: { kind: "none" },
      maxSpeakers: null
    });
  });
});

describe("metadataWithTranscription", () => {
  const metadata = {
    form_schema: { fields: [] },
    wizard: { transcription_enabled: true, transcription_model: { id: "m-1" }, origin: "chat" }
  };
  const saved = transcriptionSettingsOf(metadata);

  it("writes only what changed and keeps the wizard's other keys", () => {
    const next = metadataWithTranscription(
      metadata,
      saved,
      { ...saved, language: "auto", maxSpeakers: 4 },
      { takesAudio: true }
    );
    expect(next).toEqual({
      form_schema: { fields: [] },
      wizard: {
        transcription_enabled: true,
        transcription_model: { id: "m-1" },
        origin: "chat",
        transcription_language: "auto",
        transcription_max_speakers: 4
      }
    });
  });

  it("stores none as null and labels no speakers with it", () => {
    const next = metadataWithTranscription(metadata, saved, withSpeakerService(saved, null), {
      takesAudio: true
    });
    expect(next.wizard).toMatchObject({
      transcription_speaker_service: null,
      transcription_diarization: false
    });
  });

  it("leaves the metadata as it is when nothing changed", () => {
    expect(metadataWithTranscription(metadata, saved, saved, { takesAudio: true })).toEqual(
      metadata
    );
  });

  it("turns transcription on for a flow that takes audio", () => {
    const off = transcriptionSettingsOf(null);
    expect(metadataWithTranscription(null, off, off, { takesAudio: true })).toEqual({
      wizard: { transcription_enabled: true }
    });
  });
});

describe("speakerServiceState", () => {
  it("names why a chosen service cannot be used", () => {
    const settings = withSpeakerService(transcriptionSettingsOf(null), "svc-1");
    expect(
      speakerServiceState(settings, [service({ meets_security_classification: false })], false).lost
    ).toEqual({ reason: "classification", name: "Ordtjänst" });
    expect(speakerServiceState(settings, [service({ available: false })], false).lost).toEqual({
      reason: "disabled",
      name: "Ordtjänst"
    });
    expect(speakerServiceState(settings, [], false).lost).toEqual({
      reason: "removed",
      name: null
    });
  });

  it("labels speakers when a step names them, even when the author turned labels off", () => {
    const settings = { ...transcriptionSettingsOf(null), speakerLabels: false };
    expect(speakerServiceState(settings, [service()], true).labelled).toBe(true);
    expect(speakerServiceState(settings, [service()], false).labelled).toBe(false);
  });
});

describe("transcriptionModelMissing", () => {
  it("holds for a flow that takes audio without a model", () => {
    expect(flowTakesAudio([audioStep])).toBe(true);
    expect(transcriptionModelMissing({ modelId: null }, [audioStep])).toBe(true);
    expect(transcriptionModelMissing({ modelId: "m-1" }, [audioStep])).toBe(false);
    expect(transcriptionModelMissing({ modelId: null }, [makeStep(1)])).toBe(false);
  });
});
