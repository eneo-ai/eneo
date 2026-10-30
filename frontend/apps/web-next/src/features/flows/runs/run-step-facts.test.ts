import { describe, expect, it } from "vitest";
import {
  rejectedOutput,
  runtimeInputSummary,
  sectionReading,
  speakerMapping,
  templateProvenance,
  transcriptionFacts,
  withGivenNames
} from "./run-step-facts";

describe("sectionReading", () => {
  it("places each part in the material, in percent", () => {
    expect(
      sectionReading({
        section_manifest: {
          character_length: 200,
          sections: [
            { core: { start_char: 0, end_char: 50 } },
            { core: { start_char: 50, end_char: 200 } }
          ]
        }
      })
    ).toEqual({
      ranges: [
        { from: 0, to: 25 },
        { from: 25, to: 100 }
      ],
      result: null
    });
  });

  it("tells a result kept per part from one summarized, by the entries it holds", () => {
    const manifest = {
      character_length: 300,
      sections: [0, 100, 200].map((start) => ({
        core: { start_char: start, end_char: start + 100 }
      }))
    };
    const read = (structured: unknown) =>
      sectionReading({ section_manifest: manifest, structured })?.result;
    expect(read({ items: [{ a: 1 }, { a: 2 }, { a: 3 }] })).toBe("per_part");
    expect(read({ items: [{ a: 6 }] })).toBe("one");
    // Entries that match neither, or a result without one list, say nothing.
    expect(read({ items: [{ a: 1 }, { a: 2 }] })).toBeNull();
    expect(read({ items: [], note: "x" })).toBeNull();
    expect(read(undefined)).toBeNull();
  });

  it("reads a malformed manifest as nothing", () => {
    expect(sectionReading({ section_manifest: { character_length: 0, sections: [] } })).toBeNull();
    expect(
      sectionReading({ section_manifest: { character_length: 10, sections: [{ core: {} }] } })
    ).toBeNull();
    expect(sectionReading({ text: "kort" })).toBeNull();
  });
});

describe("rejectedOutput", () => {
  it("decodes an answer stored as escaped JSON, else keeps its text", () => {
    expect(rejectedOutput({ rejected_output: '{"svar": 1}' })).toEqual({ value: { svar: 1 } });
    expect(rejectedOutput({ rejected_output: "inte json" })).toEqual({ value: "inte json" });
    expect(rejectedOutput({ text: "ok" })).toBeNull();
  });
});

describe("templateProvenance", () => {
  it("names the template a step filled and its version", () => {
    expect(
      templateProvenance({
        template_provenance: {
          template_name: " Beslutsmall ",
          published_flow_version: 4,
          template_asset_id: "asset-1",
          checksum: "abc"
        }
      })
    ).toEqual({
      name: "Beslutsmall",
      version: 4,
      assetId: "asset-1",
      fileId: null,
      checksum: "abc"
    });
    expect(templateProvenance({ template_provenance: { template_name: " " } })).toBeNull();
  });
});

describe("runtimeInputSummary", () => {
  it("counts the files and says how much text was read out of them and in what format", () => {
    expect(
      runtimeInputSummary({
        input_payload_json: {
          runtime_input: { extracted_text_length: 1234, input_format: "document" }
        },
        runtime_input_file_ids: ["file-1", "file-2"]
      })
    ).toEqual({ fileCount: 2, extractedTextLength: 1234, inputFormat: "document" });
    expect(runtimeInputSummary({ input_payload_json: {}, runtime_input_file_ids: [] })).toBeNull();
  });
});

describe("transcriptionFacts", () => {
  it("reads how a step transcribed its audio", () => {
    expect(
      transcriptionFacts({
        input_payload_json: {
          transcription: {
            files_count: 2,
            language: "sv",
            elapsed_ms: 65_000,
            model: "speech-large",
            speaker_service: "Talartjänst",
            transcript_bytes: 2048,
            estimated_tokens: 512,
            diarization: "external",
            diarization_elapsed_ms: 4000,
            alignment: "forced"
          }
        }
      })
    ).toEqual({
      files: 2,
      language: "sv",
      elapsedMs: 65_000,
      model: "speech-large",
      speakerService: "Talartjänst",
      transcriptBytes: 2048,
      estimatedTokens: 512,
      speakers: "labelled",
      speakersElapsedMs: 4000
    });
  });

  it("says when speakers were labelled per passage or skipped, and counts the files it read", () => {
    const facts = (transcription: Record<string, unknown>) =>
      transcriptionFacts({ input_payload_json: { transcription } });
    expect(facts({ diarization: "external", alignment: "segment_only" })?.speakers).toBe(
      "reduced_precision"
    );
    expect(facts({ diarization: "skipped:no_text" })?.speakers).toBe("skipped");
    expect(facts({ diarization: null })?.speakers).toBeNull();
    expect(facts({ file_ids: ["a", "b", "c"] })?.files).toBe(3);
    expect(transcriptionFacts({ input_payload_json: { text: "x" } })).toBeNull();
  });
});

describe("speakerMapping", () => {
  const payload = {
    speaker_mapping: {
      source_step_id: "step-1",
      inventory: [{ label: "SPEAKER_00" }, { label: "SPEAKER_01" }, { label: 3 }]
    },
    structured: {
      speakers: [
        {
          label: "SPEAKER_00",
          name: "Anna Lind",
          confidence: "high",
          evidence: "Hälsar som Anna."
        },
        { label: "SPEAKER_01", name: null, confidence: "unsure" }
      ]
    }
  };

  it("names each diarized speaker as the step proposed", () => {
    expect(speakerMapping(payload)).toEqual({
      sourceStepId: "step-1",
      rows: [
        {
          label: "SPEAKER_00",
          name: "Anna Lind",
          confidence: "high",
          evidence: "Hälsar som Anna."
        },
        { label: "SPEAKER_01", name: null, confidence: "low", evidence: "" }
      ]
    });
  });

  it("is no mapping without the step's inventory", () => {
    expect(speakerMapping({ structured: payload.structured })).toBeNull();
  });

  it("puts a name a person gave over the step's, as certain, and a cleared one as unknown", () => {
    const rows = speakerMapping(payload)!.rows;
    expect(withGivenNames(rows, { SPEAKER_01: "Bo Ek" })[1]).toEqual({
      label: "SPEAKER_01",
      name: "Bo Ek",
      confidence: "high",
      evidence: ""
    });
    expect(withGivenNames(rows, { SPEAKER_00: null })[0]).toMatchObject({
      name: null,
      confidence: "low"
    });
    // A name kept as the step gave it keeps the step's evidence.
    expect(withGivenNames(rows, { SPEAKER_00: "Anna Lind" })[0]).toEqual(rows[0]);
  });
});
