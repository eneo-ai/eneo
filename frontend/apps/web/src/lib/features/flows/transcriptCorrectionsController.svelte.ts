/**
 * Shared editing lifecycle for transcript corrections, mounted by both the
 * finished-run evidence card and the paused-run review checkpoint panel.
 *
 * The controller owns the server state (occurrence list, revision compare
 * token, staleness) and the save flow: a committed line edit is diffed against
 * the RAW segment text, token-shaped edits trigger the "same correction
 * elsewhere" suggestion dialog, and every save is one replace-style request
 * guarded by the revision.
 */

import { type Eneo, type FlowRunTranscriptCorrections } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";
import type { TranscriptSegment } from "$lib/features/flows/transcriptSegments";
import {
  applyCasingPattern,
  convertTranscriptAnchors,
  diffLineEdit,
  findOccurrences,
  sortOccurrences,
  type CorrectionOccurrence,
  type OccurrenceCandidate
} from "$lib/features/flows/transcriptCorrections";
import {
  applySpeakerEditOverlay,
  sortSpeakerEdits,
  type SpeakerEdit,
  type SpeakerSpanInput
} from "$lib/features/flows/transcriptRuns";

export type SuggestionDialogState = {
  originalText: string;
  correctedText: string;
  candidates: OccurrenceCandidate[];
  /** The occurrences to save regardless of which candidates get confirmed. */
  pendingOccurrences: CorrectionOccurrence[];
};

export type TranscriptCorrectionsController = ReturnType<
  typeof createTranscriptCorrectionsController
>;

export function createTranscriptCorrectionsController(options: {
  eneo: Eneo;
  flowId: string;
  runId: string;
  /** The transcription step the corrections anchor to. */
  stepId: string;
  /** The step's stored segments, in RAW (uncorrected) form. */
  rawSegments: readonly TranscriptSegment[];
}) {
  const { eneo, flowId, runId, stepId, rawSegments } = options;

  let occurrences = $state<CorrectionOccurrence[]>([]);
  let speakerEdits = $state<SpeakerEdit[]>([]);
  let revision = $state<number | null>(null);
  let segmentsHash = $state<string | null>(rawSegments[0]?.segmentsHash ?? null);
  let stale = $state(false);
  let loaded = $state(false);
  let saving = $state(false);
  let error = $state<string | null>(null);
  let dialog = $state<SuggestionDialogState | null>(null);
  let queue: Promise<boolean> = Promise.resolve(true);
  let generation = 0;
  let blocked = $state(false);
  let pendingWrites = 0;

  function seat(set: FlowRunTranscriptCorrections | null) {
    const nextOccurrences = set?.stale
      ? [...set.occurrences]
      : convertTranscriptAnchors(set?.occurrences ?? [], rawSegments, "fromWire");
    // The generated schema marks null-span fields optional; the domain shape
    // uses explicit nulls, so normalize here once.
    const storedSpeakerEdits: SpeakerEdit[] = (set?.speaker_edits ?? []).map((edit) => ({
      segment_index: edit.segment_index,
      char_start: edit.char_start ?? null,
      char_end: edit.char_end ?? null,
      original: edit.original ?? null,
      original_speaker: edit.original_speaker,
      speaker: edit.speaker,
      decision: edit.decision ?? "confirmed"
    }));
    const nextSpeakerEdits = set?.stale
      ? storedSpeakerEdits
      : convertTranscriptAnchors(storedSpeakerEdits, rawSegments, "fromWire");
    if (!set?.stale && set?.segments_hash && !segmentsHash) segmentsHash = set.segments_hash;
    const nextRevision = set?.revision ?? null;
    const nextStale = set?.stale ?? false;
    // Keep identities stable when nothing changed: replacing the occurrence
    // array re-derives every rendered transcript line.
    if (
      nextRevision === revision &&
      nextStale === stale &&
      JSON.stringify(nextOccurrences) === JSON.stringify(occurrences) &&
      JSON.stringify(nextSpeakerEdits) === JSON.stringify(speakerEdits)
    ) {
      return;
    }
    occurrences = nextOccurrences;
    speakerEdits = nextSpeakerEdits;
    revision = nextRevision;
    stale = nextStale;
  }

  async function load(): Promise<void> {
    try {
      const sets = await eneo.flows.runs.transcriptCorrections.list({ flowId, runId });
      seat(sets.find((set) => set.step_id === stepId) ?? null);
      loaded = true;
      error = null;
    } catch (loadError) {
      console.error("Failed to load transcript corrections", loadError);
      error = getFlowRuntimeErrorMessage(
        loadError,
        m.flow_run_transcript_corrections_load_failed()
      );
    }
  }

  function persist(
    next: CorrectionOccurrence[],
    nextSpeakerEdits: SpeakerEdit[]
  ): Promise<boolean> {
    if (!loaded || stale) return Promise.resolve(false);
    // Drafts change immediately; each request captures a full immutable replacement.
    const draftOccurrences = next.map((item) => ({ ...item }));
    const draftSpeakers = nextSpeakerEdits.map((item) => ({ ...item }));
    occurrences = draftOccurrences;
    speakerEdits = draftSpeakers;
    const requested = ++generation;
    pendingWrites += 1;
    saving = true;
    queue = queue
      .then(async (previousSaved) => {
        if (!previousSaved || blocked) return false;
        try {
          const saved = await eneo.flows.runs.transcriptCorrections.save({
            flowId,
            runId,
            stepId,
            expectedRevision: revision,
            ...(segmentsHash ? { schemaVersion: 3 as const, segmentsHash } : {}),
            occurrences: convertTranscriptAnchors(
              sortOccurrences(draftOccurrences),
              rawSegments,
              "toWire"
            ),
            speakerEdits: convertTranscriptAnchors(
              sortSpeakerEdits(draftSpeakers),
              rawSegments,
              "toWire"
            )
          });
          if (saved.stale) throw new Error(m.flow_run_transcript_corrections_conflict());
          revision = saved.revision;
          if (requested === generation) seat(saved);
          error = null;
          return true;
        } catch (saveError) {
          blocked = true;
          error = getFlowRuntimeErrorMessage(
            saveError,
            m.flow_run_transcript_corrections_save_failed()
          );
          // Keep the original revision and latest local draft. Never silently rebase.
          return false;
        }
      })
      .finally(() => {
        pendingWrites -= 1;
        saving = pendingWrites > 0;
      });
    return queue;
  }

  function replaceDraft(draft: {
    occurrences: CorrectionOccurrence[];
    speakerEdits: SpeakerEdit[];
  }) {
    return persist(draft.occurrences, draft.speakerEdits);
  }

  async function flush(): Promise<boolean> {
    let observed: Promise<boolean>;
    do {
      observed = queue;
      await observed;
    } while (observed !== queue);
    return !blocked && !stale && loaded;
  }

  async function retry(): Promise<boolean> {
    if (!loaded) {
      await load();
      return loaded && !stale;
    }
    await queue;
    blocked = false;
    error = null;
    queue = Promise.resolve(true);
    return persist([...occurrences], [...speakerEdits]);
  }

  function downloadDraft() {
    const payload = {
      flowId,
      runId,
      stepId,
      schema_version: 3,
      segments_hash: segmentsHash,
      expected_revision: revision,
      occurrences: convertTranscriptAnchors(occurrences, rawSegments, "toWire"),
      speaker_edits: convertTranscriptAnchors(speakerEdits, rawSegments, "toWire")
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" })
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "osparade-rattningar.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  /** Stale occurrences anchor to replaced text; they never carry into a save. */
  function baseOccurrences(excludeSegment: number): CorrectionOccurrence[] {
    const current = stale ? [] : occurrences;
    return current.filter((occurrence) => occurrence.segment_index !== excludeSegment);
  }

  /** Stale speaker edits anchor to replaced text; they never carry into a save. */
  function baseSpeakerEdits(): SpeakerEdit[] {
    return stale ? [] : speakerEdits;
  }

  function baseAllOccurrences(): CorrectionOccurrence[] {
    return stale ? [] : occurrences;
  }

  function overlapsExisting(
    candidate: OccurrenceCandidate,
    existing: readonly CorrectionOccurrence[]
  ): boolean {
    return existing.some(
      (occurrence) =>
        occurrence.segment_index === candidate.segmentIndex &&
        occurrence.char_start < candidate.charEnd &&
        candidate.charStart < occurrence.char_end
    );
  }

  /**
   * Commit one edited line. `editedText` is the line as the editor sees it
   * (corrections applied), so the diff against the raw text yields the line's
   * full replacement occurrence, superseding its previous ones.
   *
   * `suggest: false` skips the "same correction elsewhere" dialog; multi-
   * segment turn commits use it so sequential saves never interleave with an
   * open dialog.
   */
  async function saveLine(
    segmentIndex: number,
    editedText: string,
    options: { suggest?: boolean } = {}
  ): Promise<boolean> {
    const raw = rawSegments[segmentIndex];
    if (!raw || !loaded) return false;
    const diff = diffLineEdit(raw.text, editedText);
    const next = baseOccurrences(segmentIndex);
    if (diff.occurrence) {
      next.push({ segment_index: segmentIndex, ...diff.occurrence });
    }
    if (diff.occurrence && diff.tokenShaped && options.suggest !== false) {
      const candidates = findOccurrences(rawSegments, diff.tokenShaped.originalText, {
        segmentIndex,
        charStart: diff.occurrence.char_start
      }).filter((candidate) => !overlapsExisting(candidate, next));
      if (candidates.length > 0) {
        dialog = {
          originalText: diff.tokenShaped.originalText,
          correctedText: diff.tokenShaped.correctedText,
          candidates,
          pendingOccurrences: next
        };
        // The line editor closes; the dialog decision performs the save.
        return true;
      }
    }
    return persist(next, baseSpeakerEdits());
  }

  async function confirmSuggestions(selected: OccurrenceCandidate[]): Promise<void> {
    if (!dialog) return;
    const correctedText = dialog.correctedText;
    const extra = selected.map((candidate) => ({
      segment_index: candidate.segmentIndex,
      char_start: candidate.charStart,
      char_end: candidate.charEnd,
      original: candidate.matchedText,
      corrected: applyCasingPattern(candidate.matchedText, correctedText)
    }));
    const pending = [...dialog.pendingOccurrences, ...extra];
    dialog = null;
    await persist(pending, baseSpeakerEdits());
  }

  /** "Only this line": save the edit without any of the suggested sites. */
  async function dismissSuggestions(): Promise<void> {
    if (!dialog) return;
    const pending = dialog.pendingOccurrences;
    dialog = null;
    await persist(pending, baseSpeakerEdits());
  }

  async function revertLine(segmentIndex: number): Promise<void> {
    await persist(baseOccurrences(segmentIndex), baseSpeakerEdits());
  }

  /**
   * Reassign the requested spans (or whole segments) to another speaker.
   * The overlay merge normalizes against the stored edits (last writer
   * wins) and fills the anchors from the raw segments, so one call covers
   * badge reassignments and multi-line selections alike.
   */
  async function saveSpeakerEdits(inputs: SpeakerSpanInput[]): Promise<boolean> {
    if (!loaded || inputs.length === 0) return false;
    const merged = applySpeakerEditOverlay(baseSpeakerEdits(), inputs, rawSegments);
    return persist(baseAllOccurrences(), merged);
  }

  /** Remove one stored edit, addressed by its raw anchor (null = whole line). */
  async function revertSpeakerEdit(
    segmentIndex: number,
    charStart: number | null
  ): Promise<boolean> {
    const next = baseSpeakerEdits().filter(
      (edit) => !(edit.segment_index === segmentIndex && edit.char_start === charStart)
    );
    return persist(baseAllOccurrences(), next);
  }

  return {
    /** Occurrences safe to apply; empty while the stored set is stale. */
    get occurrences(): readonly CorrectionOccurrence[] {
      return stale ? [] : occurrences;
    },
    /** Speaker edits safe to apply; empty while the stored set is stale. */
    get speakerEdits(): readonly SpeakerEdit[] {
      return stale ? [] : speakerEdits;
    },
    get staleCount(): number {
      return stale ? occurrences.length + speakerEdits.length : 0;
    },
    get saving(): boolean {
      return saving;
    },
    get error(): string | null {
      return error;
    },
    /** Editing is enabled only once the stored state is known. */
    get ready(): boolean {
      return loaded && !stale;
    },
    get dialog(): SuggestionDialogState | null {
      return dialog;
    },
    load,
    replaceDraft,
    flush,
    retry,
    downloadDraft,
    saveLine,
    revertLine,
    saveSpeakerEdits,
    revertSpeakerEdit,
    confirmSuggestions,
    dismissSuggestions,
    clearError(): void {
      if (!blocked) error = null;
    }
  };
}
