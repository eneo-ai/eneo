import { describe, expect, it } from "vitest";

import { getRuntimeInputSummary, getTemplateProvenanceSummary } from "./flowEvidenceProvenance";

describe("flowEvidenceProvenance", () => {
  it("extracts runtime input metadata for evidence rendering", () => {
    expect(
      getRuntimeInputSummary({
        runtime_input: {
          file_ids: ["file-1", "file-2"],
          extracted_text_length: 120,
          input_format: "document"
        }
      })
    ).toEqual({
      fileCount: 2,
      extractedTextLength: 120,
      inputFormat: "document"
    });
  });

  it("prefers typed runtime input file ids over payload metadata", () => {
    expect(
      getRuntimeInputSummary({
        runtime_input_file_ids: ["relational-file"],
        input_payload_json: {
          runtime_input: {
            file_ids: ["payload-file-a", "payload-file-b"],
            extracted_text_length: 120,
            input_format: "document"
          }
        }
      })
    ).toEqual({
      fileCount: 1,
      extractedTextLength: 120,
      inputFormat: "document"
    });
  });

  it("does not fall back to payload file ids when typed file ids are empty", () => {
    expect(
      getRuntimeInputSummary({
        runtime_input_file_ids: [],
        input_payload_json: {
          runtime_input: {
            file_ids: ["payload-file"],
            extracted_text_length: 120,
            input_format: "document"
          }
        }
      })
    ).toEqual({
      fileCount: 0,
      extractedTextLength: 120,
      inputFormat: "document"
    });
  });

  it("returns null when a step result has no runtime input", () => {
    expect(
      getRuntimeInputSummary({
        runtime_input_file_ids: [],
        input_payload_json: { text: "plain input" }
      })
    ).toBeNull();
  });

  it("extracts template provenance metadata for evidence rendering", () => {
    expect(
      getTemplateProvenanceSummary({
        template_provenance: {
          template_name: "Mall.docx",
          template_asset_id: "asset-1",
          template_file_id: "file-9",
          checksum: "sha256:abc",
          published_flow_version: 7
        }
      })
    ).toEqual({
      templateName: "Mall.docx",
      templateAssetId: "asset-1",
      templateFileId: "file-9",
      checksum: "sha256:abc",
      publishedFlowVersion: 7
    });
  });
});
