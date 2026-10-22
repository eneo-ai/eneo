import type { RunStep } from "./runs-api";

/**
 * What a step result records about how it worked, read from the payloads
 * the step results already carry: how it read long material part by part,
 * the answer it gave that was not accepted, the document template it
 * filled, and what was sent in at run time. A malformed record reads as
 * nothing rather than as a wrong fact.
 */

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Where each part of a step that read its material part by part sits, in percent. */
export type SectionReading = { ranges: { from: number; to: number }[] };

export function sectionReading(payload: RunStep["output_payload_json"]): SectionReading | null {
  const manifest = asObject(asObject(payload)?.section_manifest);
  const length = manifest?.character_length;
  const sections = manifest?.sections;
  if (typeof length !== "number" || length <= 0 || !Array.isArray(sections)) return null;
  const ranges: SectionReading["ranges"] = [];
  for (const section of sections) {
    const core = asObject(asObject(section)?.core);
    if (typeof core?.start_char !== "number" || typeof core.end_char !== "number") return null;
    ranges.push({
      from: Math.round((core.start_char / length) * 100),
      to: Math.round((core.end_char / length) * 100)
    });
  }
  return ranges.length > 0 ? { ranges } : null;
}

/**
 * The answer a step gave that broke its format, which the core stores as one
 * escaped string: decoded when it is JSON, else the text as it came.
 */
export function rejectedOutput(payload: RunStep["output_payload_json"]): { value: unknown } | null {
  const raw = asObject(payload)?.rejected_output;
  if (typeof raw !== "string") return null;
  try {
    return { value: JSON.parse(raw) as unknown };
  } catch {
    return { value: raw };
  }
}

export type TemplateProvenance = {
  name: string;
  version: number | null;
  assetId: string | null;
  fileId: string | null;
  checksum: string | null;
};

/** The document template a step filled, as its result records it. */
export function templateProvenance(
  payload: RunStep["output_payload_json"]
): TemplateProvenance | null {
  const provenance = asObject(asObject(payload)?.template_provenance);
  const name = provenance?.template_name;
  if (typeof name !== "string" || !name.trim()) return null;
  const text = (value: unknown) => (typeof value === "string" && value ? value : null);
  return {
    name: name.trim(),
    version:
      typeof provenance?.published_flow_version === "number"
        ? provenance.published_flow_version
        : null,
    assetId: text(provenance?.template_asset_id),
    fileId: text(provenance?.template_file_id),
    checksum: text(provenance?.checksum)
  };
}

export type RuntimeInputSummary = {
  fileCount: number;
  extractedTextLength: number | null;
  inputFormat: string | null;
};

/** What was sent in to a step at run time: how many files, the text read out of them and its format. */
export function runtimeInputSummary(
  result: Pick<RunStep, "input_payload_json" | "runtime_input_file_ids">
): RuntimeInputSummary | null {
  const runtimeInput = asObject(asObject(result.input_payload_json)?.runtime_input);
  const typedIds = result.runtime_input_file_ids ?? [];
  if (!runtimeInput && typedIds.length === 0) return null;
  const payloadIds = Array.isArray(runtimeInput?.file_ids) ? runtimeInput.file_ids : [];
  const length = runtimeInput?.extracted_text_length;
  const format = runtimeInput?.input_format;
  return {
    fileCount: typedIds.length > 0 ? typedIds.length : payloadIds.length,
    extractedTextLength: typeof length === "number" && length >= 0 ? length : null,
    inputFormat: typeof format === "string" && format ? format : null
  };
}
