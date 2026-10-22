"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { QuietBanner } from "@/components/astryx/banner";
import { TextInput } from "@/components/astryx/text-input";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { isStaleRefusal, refusalText } from "./run-messages";
import {
  editTranscriptCorrections,
  runKeys,
  transcriptCorrectionsQueryOptions,
  transcriptQueryOptions
} from "./runs-api";
import {
  clockTime,
  parseSegments,
  shownSegments,
  speakerLabels,
  speakerNamesRequest,
  type ShownSegment,
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

function SegmentLine({ segment, multiFile }: { segment: ShownSegment; multiFile: boolean }) {
  const t = useTranslations();
  const speaker = segment.name ?? segment.label ?? t("flow_runs_transcript_unknown_speaker");
  return (
    <li className="grid gap-x-3 gap-y-0.5 py-1.5 sm:grid-cols-[minmax(6rem,max-content)_1fr]">
      <span className="text-ax-text-secondary text-xs tabular-nums sm:pt-0.5">
        {multiFile
          ? t("flow_runs_transcript_time_in_file", {
              file: segment.fileIndex + 1,
              time: clockTime(segment.start)
            })
          : clockTime(segment.start)}
      </span>
      <span className="text-ax-text text-sm break-words">
        <span className="font-semibold">{speaker}:</span> {segment.text}
      </span>
    </li>
  );
}

function StepTranscript({
  flowId,
  runId,
  target,
  corrections,
  mayEdit,
  runCompleted
}: {
  flowId: string;
  runId: string;
  target: TranscriptTarget;
  corrections: TranscriptCorrections | null;
  mayEdit: boolean;
  runCompleted: boolean;
}) {
  const t = useTranslations();
  const source = useQuery(transcriptQueryOptions(flowId, runId, target));

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
  return (
    <div className="flex flex-col gap-4">
      {corrections?.stale ? (
        <QuietBanner
          status="warning"
          title={t("flow_runs_transcript_stale_title")}
          description={t("flow_runs_transcript_stale")}
          collapsible={false}
        />
      ) : null}
      {mayEdit && runCompleted && labels.length > 0 ? (
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
      <ol aria-label={t("flow_runs_transcript_lines")} className="m-0 flex flex-col p-0">
        {shown.map((segment) => (
          <SegmentLine key={segment.index} segment={segment} multiFile={multiFile} />
        ))}
      </ol>
    </div>
  );
}

/**
 * The transcripts of a run's audio steps: each line with its time and
 * speaker, with the saved corrections and speaker names applied. Someone
 * who may review flows can name the speakers once the run has completed;
 * the names are saved with the run's other transcript corrections, which
 * are kept as they are.
 */
export function RunTranscripts({
  flowId,
  runId,
  targets,
  labelFor,
  mayEdit,
  runCompleted
}: {
  flowId: string;
  runId: string;
  targets: readonly TranscriptTarget[];
  labelFor: (target: TranscriptTarget) => string;
  mayEdit: boolean;
  runCompleted: boolean;
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
          />
        </section>
      ))}
    </div>
  );
}
