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
