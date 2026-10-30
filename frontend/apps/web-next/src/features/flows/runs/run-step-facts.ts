import type { RunStep } from "./runs-api";

/**
 * What a step result records about how it worked, read from the payloads
 * the step results already carry: how it read long material part by part,
 * the answer it gave that was not accepted, the document template it
 * filled, what was sent in at run time, how it transcribed audio and whom
 * it named as the speakers. A malformed record reads as nothing rather than
 * as a wrong fact.
 */

function asObject(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * How a step read its material part by part: where each part sits, in
 * percent, and what the result holds. `result` is `per_part` when it holds
 * one entry per part and `one` when the parts were summarized into a single
 * entry (the two text processing modes, as their output shows them), or
 * null when the parts or the entries cannot be counted.
 */
export type SectionReading = {
  ranges: { from: number; to: number }[];
  result: "per_part" | "one" | null;
};

/** The entries of a section-processed result: its one list (`{ items: [...] }`). */
function resultEntries(structured: unknown): number | null {
  const record = asObject(structured);
  if (!record) return null;
  const lists = Object.values(record).filter(Array.isArray);
  return lists.length === 1 && Object.keys(record).length === 1 ? lists[0]!.length : null;
}

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
  if (ranges.length === 0) return null;
  const entries = resultEntries(asObject(payload)?.structured);
  const result =
    ranges.length < 2 || entries === null
      ? null
      : entries === ranges.length
        ? "per_part"
        : entries === 1
          ? "one"
          : null;
  return { ranges, result };
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

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function word(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** How a step transcribed its audio (`input_payload_json.transcription`). */
export type TranscriptionFacts = {
  files: number | null;
  language: string | null;
  elapsedMs: number | null;
  model: string | null;
  /** The speaker identification service that labelled the speakers, by its name then. */
  speakerService: string | null;
  transcriptBytes: number | null;
  estimatedTokens: number | null;
  /**
   * Whether speakers were labelled: `labelled`, `reduced_precision` (labelled
   * per passage, since the service could not place each word), `skipped`
   * (the transcription gave no text), or null when none was asked for.
   */
  speakers: "labelled" | "reduced_precision" | "skipped" | null;
  speakersElapsedMs: number | null;
};

export function transcriptionFacts(
  result: Pick<RunStep, "input_payload_json">
): TranscriptionFacts | null {
  const record = asObject(asObject(result.input_payload_json)?.transcription);
  if (!record) return null;
  const diarization = record.diarization;
  const alignment = record.alignment;
  const fileIds = Array.isArray(record.file_ids) ? record.file_ids.length : null;
  return {
    files: count(record.files_count) ?? fileIds,
    language: word(record.language),
    elapsedMs: count(record.elapsed_ms),
    model: word(record.model),
    speakerService: word(record.speaker_service),
    transcriptBytes: count(record.transcript_bytes),
    estimatedTokens: count(record.estimated_tokens),
    speakers:
      diarization === "external"
        ? alignment === "segment_split" || alignment === "segment_only"
          ? "reduced_precision"
          : "labelled"
        : typeof diarization === "string" && diarization.startsWith("skipped")
          ? "skipped"
          : null,
    speakersElapsedMs: count(record.diarization_elapsed_ms)
  };
}

export type SpeakerConfidence = "low" | "medium" | "high";

/** One diarized speaker of a speaker-mapping step and whom the step named. */
export type SpeakerRow = {
  label: string;
  name: string | null;
  confidence: SpeakerConfidence;
  evidence: string;
};

/**
 * The speakers a speaker-mapping step named: one row per diarized label in
 * the step's inventory (`speaker_mapping.inventory`, the discriminator: plain
 * JSON with a `speakers` key is not a mapping), with the name, confidence and
 * evidence it proposed (`structured.speakers`), and the transcription step
 * the mapping was made from.
 */
export function speakerMapping(
  payload: RunStep["output_payload_json"]
): { rows: SpeakerRow[]; sourceStepId: string | null } | null {
  const extension = asObject(asObject(payload)?.speaker_mapping);
  if (!extension) return null;
  const proposals = new Map<string, Record<string, unknown>>();
  const speakers = asObject(asObject(payload)?.structured)?.speakers;
  for (const item of Array.isArray(speakers) ? speakers : []) {
    const entry = asObject(item);
    if (entry && typeof entry.label === "string") proposals.set(entry.label, entry);
  }
  const rows: SpeakerRow[] = [];
  for (const item of Array.isArray(extension.inventory) ? extension.inventory : []) {
    const label = asObject(item)?.label;
    if (typeof label !== "string") continue;
    const proposal = proposals.get(label);
    const confidence = proposal?.confidence;
    rows.push({
      label,
      name: word(proposal?.name),
      confidence: confidence === "high" || confidence === "medium" ? confidence : "low",
      evidence: typeof proposal?.evidence === "string" ? proposal.evidence.trim() : ""
    });
  }
  if (rows.length === 0) return null;
  return { rows, sourceStepId: word(extension.source_step_id) };
}

/**
 * The rows with the names a person gave later (kept with the transcript's
 * corrections): a string replaces the step's name, null clears it, a label
 * left out keeps it. A row keeps the step's confidence and evidence while it
 * names its speaker as the step did; a name a person gave is as certain as a
 * name gets, and a cleared one is unknown. The core stores names by the
 * same rule.
 */
export function withGivenNames(
  rows: readonly SpeakerRow[],
  names: Readonly<Record<string, string | null>>
): SpeakerRow[] {
  return rows.map((row) => {
    if (!(row.label in names)) return row;
    const name = names[row.label]?.trim() || null;
    if (name === row.name) return row;
    return { ...row, name, confidence: name ? "high" : "low", evidence: "" };
  });
}
