/**
 * Reviewer-side view of a speaker-mapping checkpoint: one row per diarized
 * speaker, editable name, and the edited value the API expects back.
 */
export type SpeakerConfidence = "low" | "medium" | "high";

export type SpeakerMappingRow = {
  label: string;
  lineCount: number;
  samples: string[];
  name: string | null;
  confidence: SpeakerConfidence;
  evidence: string;
};

export type SpeakerMappingEditedValue = {
  speakers: {
    label: string;
    name: string | null;
    confidence: SpeakerConfidence;
    evidence: string;
  }[];
};

type Payload = Record<string, unknown> | null | undefined;

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function isSpeakerMappingCheckpoint(payload: Payload): boolean {
  return record(payload?.speaker_mapping) !== null;
}

export function getSpeakerMappingParticipants(payload: Payload): string[] {
  const extension = record(payload?.speaker_mapping);
  const participants = extension?.participants;
  return Array.isArray(participants)
    ? participants.filter((item): item is string => typeof item === "string" && item.trim() !== "")
    : [];
}

/** Whether the proposal may name people the conversation itself revealed. */
export function getSpeakerMappingInferNames(payload: Payload): boolean {
  return record(payload?.speaker_mapping)?.infer_names === true;
}

/** The transcription step this mapping was proposed from, when recorded. */
export function getSpeakerMappingSourceStep(payload: Payload): {
  stepId: string | null;
  stepOrder: number | null;
} {
  const extension = record(payload?.speaker_mapping);
  return {
    stepId: typeof extension?.source_step_id === "string" ? extension.source_step_id : null,
    stepOrder: typeof extension?.source_step_order === "number" ? extension.source_step_order : null
  };
}

/** Label to name for every row the reviewer has named. */
export function speakerNamesFromRows(rows: readonly SpeakerMappingRow[]): Record<string, string> {
  const names: Record<string, string> = {};
  for (const row of rows) {
    const name = row.name?.trim();
    if (name) names[row.label] = name;
  }
  return names;
}

/**
 * The names a transcript shows: a speaker-naming step's (`base`) under a
 * person's, kept with the transcript corrections. A string overrides, null
 * removes the step's name and an absent label inherits it, the same rule as
 * the backend's `effective_speaker_names`.
 */
export function effectiveSpeakerNames(
  base: Readonly<Record<string, string>>,
  overrides: Readonly<Record<string, string | null>>
): Record<string, string> {
  const names: Record<string, string> = {};
  for (const [label, name] of Object.entries({ ...base, ...overrides })) {
    if (typeof name === "string") names[label] = name;
  }
  return names;
}

function confidenceOf(value: unknown): SpeakerConfidence {
  return value === "high" || value === "medium" ? value : "low";
}

export function buildSpeakerRows(payload: Payload): SpeakerMappingRow[] {
  const extension = record(payload?.speaker_mapping);
  const inventory = Array.isArray(extension?.inventory) ? extension.inventory : [];
  const structured = record(payload?.structured);
  const proposals = Array.isArray(structured?.speakers) ? structured.speakers : [];
  const proposalByLabel = new Map<string, Record<string, unknown>>();
  for (const item of proposals) {
    const entry = record(item);
    if (entry && typeof entry.label === "string") proposalByLabel.set(entry.label, entry);
  }
  const rows: SpeakerMappingRow[] = [];
  for (const item of inventory) {
    const entry = record(item);
    if (!entry || typeof entry.label !== "string") continue;
    const proposal = proposalByLabel.get(entry.label);
    rows.push({
      label: entry.label,
      lineCount: typeof entry.line_count === "number" ? entry.line_count : 0,
      samples: Array.isArray(entry.samples)
        ? entry.samples.filter((s): s is string => typeof s === "string")
        : [],
      name: typeof proposal?.name === "string" && proposal.name.trim() ? proposal.name : null,
      confidence: confidenceOf(proposal?.confidence),
      evidence: typeof proposal?.evidence === "string" ? proposal.evidence : ""
    });
  }
  return rows;
}

/**
 * The step's own row for `row`'s speaker, out of `proposed`, while `row`
 * names that speaker as the step did; undefined once a person named or
 * cleared it otherwise.
 */
export function keptProposal(
  row: SpeakerMappingRow,
  proposed: readonly SpeakerMappingRow[]
): SpeakerMappingRow | undefined {
  const name = row.name?.trim() || null;
  return proposed.find((proposal) => proposal.label === row.label && proposal.name === name);
}

/**
 * `rows` as the server stores a review of `proposed`, the step's own rows
 * (the backend's `mapping_with_proposal_support`): a row keeps the step's
 * confidence and evidence while it names its speaker as the step did. A name
 * a person gives instead is as certain as a name gets, one they clear leaves
 * the speaker unknown, and neither keeps the step's evidence.
 */
export function withProposalSupport(
  rows: readonly SpeakerMappingRow[],
  proposed: readonly SpeakerMappingRow[]
): SpeakerMappingRow[] {
  return rows.map((row): SpeakerMappingRow => {
    const proposal = keptProposal(row, proposed);
    return proposal
      ? { ...row, confidence: proposal.confidence, evidence: proposal.evidence }
      : { ...row, confidence: row.name?.trim() ? "high" : "low", evidence: "" };
  });
}

export function buildEditedMapping(rows: SpeakerMappingRow[]): SpeakerMappingEditedValue {
  return {
    speakers: rows.map((row) => ({
      label: row.label,
      name: row.name?.trim() ? row.name.trim() : null,
      confidence: row.confidence,
      evidence: row.evidence
    }))
  };
}
