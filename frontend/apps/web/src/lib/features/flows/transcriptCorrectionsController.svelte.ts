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

import { EneoError, type Eneo, type FlowRunTranscriptCorrections } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";
import type { TranscriptSegment } from "$lib/features/flows/transcriptSegments";
import {
  applyCasingPattern,
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
  let stale = $state(false);
  let loaded = $state(false);
  let saving = $state(false);
  let error = $state<string | null>(null);
  let dialog = $state<SuggestionDialogState | null>(null);

  function seat(set: FlowRunTranscriptCorrections | null) {
    const nextOccurrences = (set?.occurrences ?? []).map((occurrence) => ({ ...occurrence }));
    // The generated schema marks null-span fields optional; the domain shape
    // uses explicit nulls, so normalize here once.
    const nextSpeakerEdits: SpeakerEdit[] = (set?.speaker_edits ?? []).map((edit) => ({
      segment_index: edit.segment_index,
      char_start: edit.char_start ?? null,
      char_end: edit.char_end ?? null,
      original: edit.original ?? null,
      original_speaker: edit.original_speaker,
      speaker: edit.speaker
    }));
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
    } catch (loadError) {
      console.error("Failed to load transcript corrections", loadError);
      error = getFlowRuntimeErrorMessage(
        loadError,
        m.flow_run_transcript_corrections_load_failed()
      );
    }
  }

  function isStaleRevision(candidate: unknown): boolean {
    return (
      candidate instanceof EneoError &&
      (candidate.response as { code?: string } | undefined)?.code ===
        "flow_transcript_corrections_stale_revision"
    );
  }

  async function persist(
    next: CorrectionOccurrence[],
    nextSpeakerEdits: SpeakerEdit[]
  ): Promise<boolean> {
    saving = true;
    error = null;
    try {
      seat(
        await eneo.flows.runs.transcriptCorrections.save({
          flowId,
          runId,
          stepId,
          expectedRevision: revision,
          occurrences: sortOccurrences(next),
          speakerEdits: sortSpeakerEdits(nextSpeakerEdits)
        })
      );
      return true;
    } catch (saveError) {
      console.error("Failed to save transcript corrections", saveError);
      if (isStaleRevision(saveError)) {
        // Another editor (the other surface, or another person) saved first;
        // reload their state instead of silently overwriting it.
        error = m.flow_run_transcript_corrections_conflict();
        await load();
      } else {
        error = getFlowRuntimeErrorMessage(
          saveError,
          m.flow_run_transcript_corrections_save_failed()
        );
      }
      return false;
    } finally {
      saving = false;
    }
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
      return loaded;
    },
    get dialog(): SuggestionDialogState | null {
      return dialog;
    },
    load,
    saveLine,
    revertLine,
    saveSpeakerEdits,
    revertSpeakerEdit,
    confirmSuggestions,
    dismissSuggestions,
    clearError(): void {
      error = null;
    }
  };
}
