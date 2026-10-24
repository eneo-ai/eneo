"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, type Ref } from "react";
import { flushSync } from "react-dom";
import { TextInput } from "@astryxdesign/core/TextInput";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { useSpace } from "@/features/spaces/use-space";
import { isStaleRefusal, refusalText } from "./run-messages";
import {
  editTranscriptCorrections,
  runKeys,
  transcriptCorrectionsQueryOptions,
  transcriptQueryOptions
} from "./runs-api";
import {
  correctionSet,
  editRequest,
  knownSpeakers,
  type EditRequest
} from "./transcript-corrections";
import { CorrectionHistory, RegenerateFromTranscript } from "./transcript-history";
import { TranscriptLines } from "./transcript-lines";
import { ReviewDraftLines, type TranscriptDraftHandle } from "./transcript-review-draft";
import { runHref } from "./runs-list";
import {
  parseSegments,
  shownSegments,
  speakerLabels,
  speakerNamesRequest,
  type TranscriptCorrections,
  type TranscriptTarget
} from "./transcript";

/** The names the reviewer gives the speakers, saved with the run's other corrections. */
function SpeakerNames({
  flowId,
  runId,
  target,
  labels,
  corrections,
  sourceHash
}: {
  flowId: string;
  runId: string;
  target: TranscriptTarget;
  labels: string[];
  corrections: TranscriptCorrections | null;
  sourceHash: string;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const formId = useId();
  const summaryRef = useRef<HTMLDivElement>(null);
  const saved = corrections?.speaker_names ?? {};
  const [names, setNames] = useState<Record<string, string>>(() =>
    Object.fromEntries(labels.map((label) => [label, saved[label] ?? ""]))
  );
  const [problem, setProblem] = useState<string | null>(null);
  const changed = labels.some((label) => (names[label] ?? "").trim() !== (saved[label] ?? ""));

  const save = useMutation({
    mutationFn: () =>
      editTranscriptCorrections(
        flowId,
        runId,
        target.stepId,
        speakerNamesRequest(corrections, sourceHash, names)
      ),
    onSuccess: () => {
      setProblem(null);
      void queryClient.invalidateQueries({ queryKey: runKeys.run(flowId, runId) });
      announce(t("flow_runs_transcript_names_saved"));
    },
    onError: (error) => {
      if (isStaleRefusal(error)) {
        void queryClient.invalidateQueries({ queryKey: runKeys.run(flowId, runId) });
      }
      flushSync(() => setProblem(refusalText(error, t)));
      summaryRef.current?.focus();
    }
  });

  return (
    <form
      id={formId}
      noValidate
      className="flex flex-col gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (save.isPending) return;
        if (changed) save.mutate();
        else announce(t("flow_runs_transcript_names_unchanged"));
      }}
    >
      <p className="text-ax-text-secondary text-sm">{t("flow_runs_transcript_names_hint")}</p>
      <div
        ref={summaryRef}
        tabIndex={-1}
        className="focus-visible:outline-ring rounded-ax-inner outline-none focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        {problem ? (
          <Banner
            role="alert"
            status="error"
            title={t("flow_runs_transcript_names_not_saved")}
            description={problem}
            collapsible={false}
          />
        ) : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {labels.map((label) => (
          <TextInput
            key={label}
            label={t("flow_runs_transcript_name_for", { label })}
            value={names[label] ?? ""}
            onChange={(value) => setNames((current) => ({ ...current, [label]: value }))}
            width="100%"
          />
        ))}
      </div>
      <div>
        <Button
          type="submit"
          label={t("flow_runs_transcript_names_save")}
          isLoading={save.isPending}
          isInterruptible
        />
      </div>
    </form>
  );
}

function StepTranscript({
  flowId,
  runId,
  target,
  corrections,
  mayEdit,
  runCompleted,
  runRevision,
  review = false,
  onUnsavedChange,
  draftRef
}: {
  flowId: string;
  runId: string;
  target: TranscriptTarget;
  corrections: TranscriptCorrections | null;
  mayEdit: boolean;
  runCompleted: boolean;
  runRevision: number | null;
  /** Shown in a review checkpoint: the lines can be corrected before the run goes on. */
  review?: boolean;
  onUnsavedChange?: (unsaved: boolean) => void;
  /** In a review: the draft of the corrections, which the review flushes before approving. */
  draftRef?: Ref<TranscriptDraftHandle>;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const { user } = useAppContext();
  const userId = user.id;
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  const source = useQuery(transcriptQueryOptions(flowId, runId, target));
  const correctionsKey = runKeys.corrections(flowId, runId);
  const save = useMutation({
    mutationFn: (body: EditRequest) =>
      editTranscriptCorrections(flowId, runId, target.stepId, body),
    onSuccess: (saved) => {
      // The step's set as saved; the others stay as they are. The save is a
      // new version in the step's history.
      queryClient.setQueryData<TranscriptCorrections[]>(correctionsKey, (current) =>
        current ? [...current.filter((item) => item.step_id !== target.stepId), saved] : [saved]
      );
      void queryClient.invalidateQueries({
        queryKey: runKeys.revisions(flowId, runId, target.stepId)
      });
    }
  });

  if (source.isPending) return <LoadingState rows={3} label={t("flow_runs_transcript_loading")} />;
  if (source.isError) {
    return (
      <ListError
        error={source.error}
        title={t("flow_runs_transcript_failed")}
        onRetry={() => void source.refetch()}
        isRetrying={source.isFetching}
      />
    );
  }
  if (source.data.status !== "present") {
    return (
      <p className="text-ax-text-secondary text-sm">
        {source.data.status === "omitted" && source.data.tooLarge
          ? t("flow_runs_transcript_omitted")
          : t("flow_runs_transcript_unavailable")}
      </p>
    );
  }
  const segments = parseSegments(source.data.segments);
  const shown = shownSegments(segments, corrections);
  const labels = speakerLabels(shown);
  const multiFile = new Set(shown.map((segment) => segment.fileIndex)).size > 1;
  const sourceHash = source.data.sourceHash;
  const editable = mayEdit && (runCompleted || review) && !corrections?.stale;
  if (review && editable) {
    // A review corrects a local draft that saves itself.
    return (
      <ReviewDraftLines
        flowId={flowId}
        runId={runId}
        target={target}
        corrections={corrections}
        segments={segments}
        sourceHash={sourceHash}
        speakerReview={source.data.speakerReview}
        onUnsavedChange={onUnsavedChange}
        draftRef={draftRef}
      />
    );
  }
  return (
    <TranscriptLines
      flowId={flowId}
      runId={runId}
      target={target}
      shown={shown}
      sourceHash={sourceHash}
      multiFile={multiFile}
      speakerReview={source.data.speakerReview}
      onUnsavedChange={onUnsavedChange}
      editing={
        editable
          ? {
              set: correctionSet(corrections, segments),
              speakers: knownSpeakers(segments, corrections?.speaker_edits ?? []),
              saving: save.isPending,
              save: async (next, done) => {
                try {
                  await save.mutateAsync(editRequest(corrections, next, segments, sourceHash));
                  announce(done);
                  return null;
                } catch (error) {
                  if (isStaleRefusal(error)) {
                    void queryClient.invalidateQueries({ queryKey: correctionsKey });
                    void queryClient.invalidateQueries({
                      queryKey: runKeys.revisions(flowId, runId, target.stepId)
                    });
                  }
                  return refusalText(error, t);
                }
              }
            }
          : null
      }
    >
      {corrections?.stale ? (
        <Banner
          status="warning"
          title={t("flow_runs_transcript_stale_title")}
          description={t("flow_runs_transcript_stale")}
          collapsible={false}
        />
      ) : null}
      {mayEdit && runCompleted && !review && corrections && !corrections.stale ? (
        <div className="flex flex-col gap-3">
          <CorrectionHistory flowId={flowId} runId={runId} stepId={target.stepId} userId={userId} />
          {runRevision !== null ? (
            <RegenerateFromTranscript
              flowId={flowId}
              runId={runId}
              stepId={target.stepId}
              runRevision={runRevision}
              correctionRevision={corrections.revision}
              sourceHash={sourceHash}
              runHref={(id) => runHref(routeId, flowId, id)}
            />
          ) : null}
        </div>
      ) : null}
      {mayEdit && runCompleted && !review && labels.length > 0 ? (
        <SpeakerNames
          key={`${corrections?.revision ?? 0}`}
          flowId={flowId}
          runId={runId}
          target={target}
          labels={labels}
          corrections={corrections}
          sourceHash={source.data.sourceHash}
        />
      ) : null}
    </TranscriptLines>
  );
}

/**
 * The transcripts of a run's audio steps: each line with its time and
 * speaker, with the saved corrections and speaker names applied, playable
 * from any line. Someone who may review flows can, once the run has
 * completed, correct a line's text (and revert it) and name the speakers;
 * each change is saved with the step's other corrections, which are kept as
 * they are.
 */
export function RunTranscripts({
  flowId,
  runId,
  targets,
  labelFor,
  mayEdit,
  runCompleted,
  runRevision = null
}: {
  flowId: string;
  runId: string;
  targets: readonly TranscriptTarget[];
  labelFor: (target: TranscriptTarget) => string;
  mayEdit: boolean;
  runCompleted: boolean;
  /** The run's revision, which starting a run from its reviewed transcript is fenced by. */
  runRevision?: number | null;
}) {
  const t = useTranslations();
  const corrections = useQuery({
    ...transcriptCorrectionsQueryOptions(flowId, runId),
    enabled: targets.length > 0
  });
  if (targets.length === 0) return null;
  if (corrections.isPending) return <LoadingState rows={2} />;
  if (corrections.isError) {
    return (
      <ListError
        error={corrections.error}
        title={t("flow_runs_transcript_failed")}
        onRetry={() => void corrections.refetch()}
        isRetrying={corrections.isFetching}
      />
    );
  }
  return (
    <div className="flex flex-col gap-6">
      {targets.map((target) => (
        <section key={target.stepId} className="flex flex-col gap-2">
          <h3 className="text-ax-text text-base font-semibold">{labelFor(target)}</h3>
          <StepTranscript
            flowId={flowId}
            runId={runId}
            target={target}
            corrections={corrections.data.find((item) => item.step_id === target.stepId) ?? null}
            mayEdit={mayEdit}
            runCompleted={runCompleted}
            runRevision={runRevision}
          />
        </section>
      ))}
    </div>
  );
}

/**
 * The transcript a review checkpoint is about, inside the review: someone
 * who may decide the review corrects its lines and speakers before
 * approving, as a draft that saves itself, and the corrections are saved
 * with the run, so they hold for the steps after the review and for the
 * finished run.
 */
export function ReviewTranscript({
  flowId,
  runId,
  target,
  mayEdit,
  onUnsavedChange,
  draftRef
}: {
  flowId: string;
  runId: string;
  target: TranscriptTarget;
  mayEdit: boolean;
  /** Tells the review whether an edit of the transcript is not saved yet. */
  onUnsavedChange?: (unsaved: boolean) => void;
  /** The corrections' draft, which the review flushes before it approves. */
  draftRef?: Ref<TranscriptDraftHandle>;
}) {
  const t = useTranslations();
  const corrections = useQuery(transcriptCorrectionsQueryOptions(flowId, runId));
  if (corrections.isPending) return <LoadingState rows={2} />;
  if (corrections.isError) {
    return (
      <ListError
        error={corrections.error}
        title={t("flow_runs_transcript_failed")}
        onRetry={() => void corrections.refetch()}
        isRetrying={corrections.isFetching}
      />
    );
  }
  return (
    <StepTranscript
      flowId={flowId}
      runId={runId}
      target={target}
      corrections={corrections.data.find((item) => item.step_id === target.stepId) ?? null}
      mayEdit={mayEdit}
      runCompleted={false}
      runRevision={null}
      review
      onUnsavedChange={onUnsavedChange}
      draftRef={draftRef}
    />
  );
}
