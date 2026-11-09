import { describe, expect, it } from "vitest";
import { makeStep } from "./flow-fixtures";
import {
  flowTakesAudio,
  liveModelState,
  liveModels,
  metadataWithTranscription,
  speakerServiceState,
  transcriptionModelMissing,
  transcriptionSettingsOf,
  withSpeakerService,
  type SpeakerServiceLink,
  type TranscriptionModelLink
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
      maxSpeakers: null,
      liveModelId: null
    });
  });

  it("reads the live model, and a blank one as none", () => {
    const read = (live: unknown) =>
      transcriptionSettingsOf({ wizard: { transcription_live_model: live } }).liveModelId;
    expect(read({ id: "live-1" })).toBe("live-1");
    expect(read({ id: " " })).toBeNull();
    expect(read(null)).toBeNull();
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

  it("stores a chosen live model, and removes it when the author chooses none", () => {
    const chosen = metadataWithTranscription(
      metadata,
      saved,
      { ...saved, liveModelId: "live-1" },
      { takesAudio: true }
    );
    expect(chosen.wizard).toMatchObject({ transcription_live_model: { id: "live-1" } });

    const fromChosen = transcriptionSettingsOf(chosen);
    const none = metadataWithTranscription(
      chosen,
      fromChosen,
      { ...fromChosen, liveModelId: null },
      { takesAudio: true }
    );
    expect(none).toEqual(metadata);
  });

  it("keeps the chosen live model while the transcription model moves onto it and away", () => {
    // A/B, then B/B (reads as the same model), then C/B: B stays the author's choice.
    const ab = {
      ...metadata,
      wizard: { ...metadata.wizard, transcription_live_model: { id: "b" } }
    };
    const abSettings = transcriptionSettingsOf(ab);
    const bb = metadataWithTranscription(
      ab,
      abSettings,
      { ...abSettings, modelId: "b" },
      {
        takesAudio: true
      }
    );
    const bbSettings = transcriptionSettingsOf(bb);
    const cb = metadataWithTranscription(
      bb,
      bbSettings,
      { ...bbSettings, modelId: "c" },
      {
        takesAudio: true
      }
    );
    expect([bb.wizard, cb.wizard]).toMatchObject([
      { transcription_model: { id: "b" }, transcription_live_model: { id: "b" } },
      { transcription_model: { id: "c" }, transcription_live_model: { id: "b" } }
    ]);
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

describe("liveModelState", () => {
  const model = (overrides: Partial<TranscriptionModelLink> = {}): TranscriptionModelLink => ({
    id: "whisper",
    name: "kb-whisper-large",
    supports_realtime: false,
    can_access: true,
    ...overrides
  });
  const whisper = model();
  const live = model({ id: "live", name: "pianissimo-sv-live", supports_realtime: true });
  const settings = (modelId: string | null, liveModelId: string | null) => ({
    modelId,
    liveModelId
  });

  it("offers only the models the space may stream through", () => {
    expect(liveModels([whisper, live, { ...live, id: "off", can_access: false }])).toEqual([live]);
  });

  it("leaves the preview to the transcription model when the flow chose none", () => {
    expect(liveModelState(settings("whisper", null), [whisper, live])).toEqual({
      kind: "transcription_model",
      streams: false
    });
    expect(liveModelState(settings("live", null), [whisper, live])).toEqual({
      kind: "transcription_model",
      streams: true
    });
    expect(liveModelState(settings(null, null), [live])).toEqual({
      kind: "transcription_model",
      streams: false
    });
  });

  it("names the chosen live model; the transcription model again is no separate choice", () => {
    expect(liveModelState(settings("whisper", "live"), [whisper, live])).toEqual({
      kind: "picked",
      model: live
    });
    expect(liveModelState(settings("live", "live"), [live])).toEqual({
      kind: "transcription_model",
      streams: true
    });
    expect(liveModelState(settings("whisper", "whisper"), [whisper])).toEqual({
      kind: "transcription_model",
      streams: false
    });
  });

  it("keeps a chosen live model the space can no longer stream through, with why", () => {
    expect(liveModelState(settings("whisper", "live"), [whisper])).toEqual({
      kind: "lost",
      model: null
    });
    const revoked = { ...live, can_access: false };
    expect(liveModelState(settings("whisper", "live"), [whisper, revoked])).toEqual({
      kind: "lost",
      model: revoked
    });
    const batchOnly = { ...live, supports_realtime: false };
    expect(liveModelState(settings("whisper", "live"), [whisper, batchOnly])).toEqual({
      kind: "lost",
      model: batchOnly
    });
  });
});
