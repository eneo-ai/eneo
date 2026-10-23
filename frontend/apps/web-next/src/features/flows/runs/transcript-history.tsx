"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Text } from "@astryxdesign/core/Text";
import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { ClientTime } from "@/components/composites/client-time";
import { StatusLabel } from "@/components/composites/status-label";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { refusalText } from "./run-messages";
import { runStatusView, shouldPoll } from "./run-status";
import {
  getRunStatus,
  newIdempotencyKey,
  regenerateTranscript,
  transcriptRevisionsQueryOptions,
  type CorrectionRevision,
  type TranscriptRegeneration
} from "./runs-api";

type Translator = ReturnType<typeof useTranslations>;

/** Who saved a version: the signed-in person, someone else, or a service key by its name. */
export function revisionAuthor(
  revision: CorrectionRevision,
  userId: string,
  t: Translator
): string {
  if (revision.edited_by_principal_type === "service_key") {
    return (
      revision.edited_by_service_principal?.display_name?.trim() ||
      t("flow_runs_started_by_service_key")
    );
  }
  return revision.edited_by_user_id === userId
    ? t("flow_transcript_history_by_you")
    : t("flow_runs_started_by_person");
}

/** What a version holds: its text corrections, speaker changes and names. */
export function revisionContents(revision: CorrectionRevision, t: Translator): string {
  const names = Object.values(revision.speaker_names ?? {}).filter(
    (name) => typeof name === "string" && name.trim()
  ).length;
  return t("flow_transcript_history_contents", {
    corrections: revision.occurrences_json.length,
    speakers: revision.speaker_edits_json.length,
    names
  });
}

/**
 * Every saved version of a step's transcript corrections, oldest first: when
 * it was saved, by whom, and what it held. Read when it is opened.
 */
export function CorrectionHistory({
  flowId,
  runId,
  stepId,
  userId
}: {
  flowId: string;
  runId: string;
  stepId: string;
  userId: string;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const history = useInfiniteQuery({
    ...transcriptRevisionsQueryOptions(flowId, runId, stepId),
    enabled: open
  });
  const items = history.data?.pages.flatMap((page) => page.items) ?? [];

  let body: React.ReactNode = null;
  if (open) {
    if (history.isPending)
      body = <LoadingState rows={2} label={t("flow_transcript_history_loading")} />;
    else if (history.isError) {
      body = (
        <ListError
          error={history.error}
          title={t("flow_transcript_history_failed")}
          onRetry={() => void history.refetch()}
          isRetrying={history.isFetching}
        />
      );
    } else if (items.length === 0) {
      body = <Text type="supporting">{t("flow_transcript_history_empty")}</Text>;
    } else {
      body = (
        <div className="flex flex-col gap-2">
          <ol
            aria-label={t("flow_transcript_history_heading")}
            className="m-0 flex flex-col gap-1 p-0"
          >
            {items.map((revision) => (
              <li key={revision.id} className="border-ax-border border-t py-1.5 first:border-t-0">
                <Text as="p">
                  <span className="font-semibold">
                    {t("flow_transcript_history_version", { revision: revision.revision })}
                  </span>{" "}
                  · <ClientTime value={revision.created_at} format="date_time" /> ·{" "}
                  {revisionAuthor(revision, userId, t)}
                </Text>
                <Text type="supporting" as="p">
                  {revisionContents(revision, t)}
                </Text>
              </li>
            ))}
          </ol>
          {history.hasNextPage ? (
            <div>
              <Button
                label={t("flow_transcript_history_more")}
                size="sm"
                isLoading={history.isFetchingNextPage}
                isInterruptible
                onClick={() => {
                  if (!history.isFetchingNextPage) void history.fetchNextPage();
                }}
              />
            </div>
          ) : null}
        </div>
      );
    }
  }

  return (
    <Collapsible
      trigger={
        <span className="text-sm font-semibold">{t("flow_transcript_history_heading")}</span>
      }
      isOpen={open}
      onOpenChange={setOpen}
      chevronPosition="start"
    >
      <div className="pt-2">{body}</div>
    </Collapsible>
  );
}

/** The status of a run started from the reviewed transcript, followed until it settles. */
function StartedRun({
  flowId,
  started,
  href
}: {
  flowId: string;
  started: TranscriptRegeneration;
  href: string;
}) {
  const t = useTranslations();
  const status = useQuery({
    queryKey: ["flows", flowId, "runs", started.run.id, "regenerated-status"],
    queryFn: ({ signal }) => getRunStatus(flowId, started.run.id, signal),
    refetchInterval: (query) =>
      shouldPoll(query.state.data?.status ?? started.run.status) ? 5_000 : false
  });
  const view = runStatusView(status.data?.status ?? started.run.status);
  return (
    <Banner
      status="success"
      title={
        started.created
          ? t("flow_transcript_regenerate_started")
          : t("flow_transcript_regenerate_replayed")
      }
      description={t("flow_transcript_regenerate_started_hint")}
      endContent={
        <Link href={href} className="text-ax-text text-sm font-semibold underline">
          {t("flow_transcript_regenerate_open")}
        </Link>
      }
      collapsible={false}
    >
      <span className="flex items-center gap-2 text-sm">
        {t("flow_transcript_regenerate_status")}{" "}
        <StatusLabel status={view.tone} label={t(view.labelKey)} isPulsing={view.isPulsing} />
      </span>
    </Banner>
  );
}

/**
 * Starts a new run of the flow from the reviewed transcript: the corrected
 * transcription is taken as it stands, nothing is transcribed again, and the
 * later steps run anew. The new run's status shows until it settles.
 */
export function RegenerateFromTranscript({
  flowId,
  runId,
  stepId,
  runRevision,
  correctionRevision,
  sourceHash,
  runHref
}: {
  flowId: string;
  runId: string;
  stepId: string;
  runRevision: number;
  correctionRevision: number | null;
  sourceHash: string;
  runHref: (runId: string) => string;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const lastRequest = useRef<{ body: string; key: string } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => {
      const body = {
        expected_run_revision: runRevision,
        expected_correction_revision: correctionRevision,
        segments_hash: sourceHash
      };
      // The same request keeps its key, so a lost answer cannot start two runs.
      const serialized = JSON.stringify(body);
      const key =
        lastRequest.current?.body === serialized ? lastRequest.current.key : newIdempotencyKey();
      lastRequest.current = { body: serialized, key };
      return regenerateTranscript(flowId, runId, stepId, body, key);
    },
    onMutate: () => setProblem(null),
    onSuccess: () => announce(t("flow_transcript_regenerate_started")),
    onError: (error) => setProblem(refusalText(error, t))
  });

  return (
    <div className="flex flex-col gap-2">
      <Text type="supporting" as="p">
        {t("flow_transcript_regenerate_hint")}
      </Text>
      {problem ? (
        <Banner
          status="error"
          title={t("flow_transcript_regenerate_failed")}
          description={problem}
          collapsible={false}
        />
      ) : null}
      {start.data ? (
        <StartedRun flowId={flowId} started={start.data} href={runHref(start.data.run.id)} />
      ) : (
        <div>
          <Button
            label={t("flow_transcript_regenerate")}
            isLoading={start.isPending}
            isInterruptible
            onClick={() => {
              if (!start.isPending) start.mutate();
            }}
          />
        </div>
      )}
    </div>
  );
}
