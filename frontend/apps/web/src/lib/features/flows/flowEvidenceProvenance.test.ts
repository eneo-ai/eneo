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
