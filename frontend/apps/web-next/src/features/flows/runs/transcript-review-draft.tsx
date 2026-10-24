"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Text } from "@astryxdesign/core/Text";
import { useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type Ref
} from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";
import { isStaleRefusal, refusalText } from "./run-messages";
import { editTranscriptCorrections, runKeys, type TranscriptSpeakerReview } from "./runs-api";
import {
  shownSegmentsOf,
  type TranscriptCorrections,
  type TranscriptSegment,
  type TranscriptTarget
} from "./transcript";
import { correctionSet, editRequest, knownSpeakers } from "./transcript-corrections";
import { CorrectionsDraft, type DraftState } from "./transcript-draft";
import { saveText } from "./transcript-export";
import { TranscriptLines } from "./transcript-lines";

/** What a review asks of the transcript's draft before it approves. */
export type TranscriptDraftHandle = {
  /** Sends what waits; true once every correction is saved. */
  flush: () => Promise<boolean>;
};

/** The id of the draft's retry button, which a held approval moves focus to. */
export function draftRetryId(stepId: string): string {
  return `transcript-draft-retry-${stepId}`;
}

/** What a save is fenced by: the revision the draft's changes build on. */
function fence(revision: number | null, segmentsHash: string) {
  return revision === null ? null : { revision, segments_hash: segmentsHash };
}

/**
 * The draft as the save request that was not accepted, with where it belongs:
 * what support needs to apply it later, and what the reviewer keeps.
 */
function draftFile(
  ids: { flowId: string; runId: string; stepId: string },
  state: DraftState,
  segments: readonly TranscriptSegment[],
  segmentsHash: string
): string {
  const body = editRequest(fence(state.revision, segmentsHash), state.set, segments, segmentsHash);
  return JSON.stringify(
    { flow_id: ids.flowId, run_id: ids.runId, step_id: ids.stepId, ...body },
    null,
    2
  );
}

/**
 * How the draft stands: saving, or, after a failed save, why, that the
 * changes are still here, and the way on: save again, download the draft,
 * or (when someone else saved meanwhile) throw the changes away for theirs.
 */
function DraftStatusNote({
  state,
  stepId,
  onRetry,
  onDownload,
  onDiscard
}: {
  state: DraftState;
  stepId: string;
  onRetry: () => void;
  onDownload: () => void;
  onDiscard: () => void;
}) {
  const t = useTranslations();
  if (state.status === "waiting" || state.status === "saving") {
    return (
      <Text type="supporting" as="p">
        {t("flow_transcript_draft_saving")}
      </Text>
    );
  }
  if (state.status !== "failed") return null;
  const stale = isStaleRefusal(state.problem);
  return (
    <Banner
      status="error"
      title={t("flow_transcript_draft_failed_title")}
      description={`${refusalText(state.problem, t)} ${t("flow_transcript_draft_kept")}`}
      collapsible={false}
    >
      <div className="flex flex-wrap gap-2">
        <Button
          id={draftRetryId(stepId)}
          label={t("flow_transcript_draft_retry")}
          size="sm"
          onClick={onRetry}
        />
        <Button
          label={t("flow_transcript_draft_download")}
          icon={<Download aria-hidden="true" />}
          size="sm"
          onClick={onDownload}
        />
        {stale ? (
          <Button
            label={t("flow_transcript_draft_discard")}
            size="sm"
            variant="ghost"
            onClick={onDiscard}
          />
        ) : null}
      </div>
    </Banner>
  );
}

/**
 * The transcript lines of a review, corrected as a local draft: each change
 * shows at once and saves itself a moment later (`CorrectionsDraft`). A
 * failed save keeps the draft on the page, says so (announced once), and
 * offers to save again or download the draft. Leaving the page, or hiding
 * it, sends what waits, and the browser warns before it closes with changes
 * not saved. The review flushes the draft before it approves (`draftRef`).
 */
export function ReviewDraftLines({
  flowId,
  runId,
  target,
  corrections,
  segments,
  sourceHash,
  speakerReview,
  onUnsavedChange,
  draftRef,
  children
}: {
  flowId: string;
  runId: string;
  target: TranscriptTarget;
  corrections: TranscriptCorrections | null;
  segments: TranscriptSegment[];
  sourceHash: string;
  speakerReview: TranscriptSpeakerReview | null;
  onUnsavedChange?: (unsaved: boolean) => void;
  draftRef?: Ref<TranscriptDraftHandle>;
  children?: React.ReactNode;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const correctionsKey = runKeys.corrections(flowId, runId);
  const segmentsHash = corrections?.segments_hash ?? sourceHash;

  const [draft] = useState(
    () =>
      new CorrectionsDraft(
        correctionSet(corrections, segments),
        corrections?.revision ?? null,
        () => Promise.reject(new Error("The draft saves once the page has rendered."))
      )
  );
  // Each render's request: the step's lines and the hash the corrections anchor to.
  useEffect(() => {
    draft.setSave(async (set, revision) => {
      try {
        const saved = await editTranscriptCorrections(
          flowId,
          runId,
          target.stepId,
          editRequest(fence(revision, segmentsHash), set, segments, segmentsHash)
        );
        // The step's set as saved; the others stay as they are. The save is a
        // new version in the step's history.
        queryClient.setQueryData<TranscriptCorrections[]>(correctionsKey, (current) =>
          current ? [...current.filter((item) => item.step_id !== target.stepId), saved] : [saved]
        );
        void queryClient.invalidateQueries({
          queryKey: runKeys.revisions(flowId, runId, target.stepId)
        });
        return saved.revision;
      } catch (error) {
        // Someone saved first: read theirs, which the reviewer may take over.
        if (isStaleRefusal(error)) {
          void queryClient.invalidateQueries({ queryKey: correctionsKey });
          void queryClient.invalidateQueries({
            queryKey: runKeys.revisions(flowId, runId, target.stepId)
          });
        }
        throw error;
      }
    });
  });
  const state = useSyncExternalStore(draft.subscribe, draft.getSnapshot, draft.getSnapshot);

  // What the server holds, taken over while the draft holds no changes.
  useEffect(() => {
    draft.sync(correctionSet(corrections, segments), corrections?.revision ?? null);
  }, [draft, corrections, segments]);

  // Leaving the page, or hiding it, sends what waits.
  useEffect(() => {
    const send = () => {
      if (document.visibilityState === "hidden") void draft.flush();
    };
    const leave = () => void draft.flush();
    document.addEventListener("visibilitychange", send);
    window.addEventListener("pagehide", leave);
    return () => {
      document.removeEventListener("visibilitychange", send);
      window.removeEventListener("pagehide", leave);
      void draft.flush();
    };
  }, [draft]);

  // A failed save is told once, as it happens.
  useEffect(() => {
    let failed = draft.getSnapshot().status === "failed";
    return draft.subscribe(() => {
      const now = draft.getSnapshot().status === "failed";
      if (now && !failed) announce(t("flow_transcript_draft_failed_title"));
      failed = now;
    });
  }, [draft, announce, t]);

  useImperativeHandle(draftRef, () => ({ flush: () => draft.flush() }), [draft]);
  useBeforeUnloadWarning(state.status !== "saved");

  const [editorUnsaved, setEditorUnsaved] = useState(false);
  const unsaved = editorUnsaved || state.status === "failed";
  const tellUnsaved = useRef(onUnsavedChange);
  useEffect(() => {
    tellUnsaved.current = onUnsavedChange;
  });
  useEffect(() => {
    tellUnsaved.current?.(unsaved);
  }, [unsaved]);

  const shown = useMemo(() => shownSegmentsOf(segments, state.set), [segments, state.set]);
  return (
    <TranscriptLines
      flowId={flowId}
      runId={runId}
      target={target}
      shown={shown}
      sourceHash={sourceHash}
      multiFile={new Set(shown.map((segment) => segment.fileIndex)).size > 1}
      speakerReview={speakerReview}
      onUnsavedChange={setEditorUnsaved}
      editing={{
        set: state.set,
        speakers: knownSpeakers(segments, state.set.speakerEdits),
        // A change is the draft's at once; nothing waits on the server.
        saving: false,
        save: async (next, done) => {
          draft.change(next);
          announce(done);
          return null;
        }
      }}
    >
      {children}
      <DraftStatusNote
        state={state}
        stepId={target.stepId}
        onRetry={() => void draft.retry()}
        onDownload={() =>
          saveText(
            draftFile({ flowId, runId, stepId: target.stepId }, state, segments, segmentsHash),
            t("flow_transcript_draft_file"),
            "application/json"
          )
        }
        onDiscard={() => {
          draft.discard(correctionSet(corrections, segments), corrections?.revision ?? null);
          announce(t("flow_transcript_draft_discarded"));
        }}
      />
    </TranscriptLines>
  );
}
