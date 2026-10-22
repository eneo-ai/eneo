import { describe, expect, it } from "vitest";
import {
  rejectedOutput,
  runtimeInputSummary,
  sectionReading,
  templateProvenance
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
      ]
    });
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
