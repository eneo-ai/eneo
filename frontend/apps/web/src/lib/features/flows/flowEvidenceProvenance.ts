export type RuntimeInputSummary = {
  fileCount: number;
  extractedTextLength: number | null;
  inputFormat: string | null;
};

export type TemplateProvenanceSummary = {
  templateName: string;
  templateAssetId: string | null;
  templateFileId: string | null;
  checksum: string | null;
  publishedFlowVersion: number | null;
};

function asObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

export function getRuntimeInputSummary(payload: unknown): RuntimeInputSummary | null {
  const root = asObject(payload);
  const runtimeInput = asObject(root?.runtime_input);
  if (!runtimeInput) return null;

  const fileIds = Array.isArray(runtimeInput.file_ids)
    ? runtimeInput.file_ids.filter((value): value is string => typeof value === "string")
    : [];

  return {
    fileCount: fileIds.length,
    extractedTextLength:
      typeof runtimeInput.extracted_text_length === "number"
        ? runtimeInput.extracted_text_length
        : null,
    inputFormat: typeof runtimeInput.input_format === "string" ? runtimeInput.input_format : null
  };
}

export function getTemplateProvenanceSummary(payload: unknown): TemplateProvenanceSummary | null {
  const root = asObject(payload);
  const provenance = asObject(root?.template_provenance);
  if (!provenance) return null;

  const templateName =
    typeof provenance.template_name === "string" && provenance.template_name.trim().length > 0
      ? provenance.template_name
      : null;

  if (!templateName) return null;

  return {
    templateName,
    templateAssetId:
      typeof provenance.template_asset_id === "string" ? provenance.template_asset_id : null,
    templateFileId:
      typeof provenance.template_file_id === "string" ? provenance.template_file_id : null,
    checksum: typeof provenance.checksum === "string" ? provenance.checksum : null,
    publishedFlowVersion:
      typeof provenance.published_flow_version === "number"
        ? provenance.published_flow_version
        : null
  };
}
