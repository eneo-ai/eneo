"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { JsonValue } from "./run-json";
import { reviewEditsQueryOptions, type ReviewEdit } from "./review-extras-api";
import type { ReviewCheckpoint } from "./runs-api";

type Payload = Record<string, unknown> | null;

/** The output a payload holds, as the review shows it: text as text, JSON as a value. */
function PayloadValue({
  payload,
  outputType
}: {
  payload: Payload;
  outputType: ReviewCheckpoint["output_type"];
}) {
  const t = useTranslations();
  if (!payload)
    return <p className="text-ax-text-secondary text-sm">{t("flow_runs_value_empty")}</p>;
  if (outputType === "json" && "structured" in payload)
    return <JsonValue value={payload.structured} />;
  const text = typeof payload.text === "string" ? payload.text : "";
  return (
    <p className="bg-ax-sunken rounded-ax-inner text-ax-text max-h-80 overflow-auto p-2 text-sm break-words whitespace-pre-wrap">
      {text}
    </p>
  );
}

function editorName(edit: ReviewEdit, userId: string, t: ReturnType<typeof useTranslations>) {
  const service = edit.edited_by_service_principal?.display_name?.trim();
  if (service) return t("flow_run_extras_history_by_service", { name: service });
  if (edit.edited_by_user_id && edit.edited_by_user_id === userId) {
    return t("flow_run_extras_history_by_you");
  }
  // The API names no other person, and a piece of an id names nobody.
  return t("flow_run_extras_history_by_other");
}

function EditRow({
  edit,
  before,
  beforeIsOriginal,
  outputType
}: {
  edit: ReviewEdit;
  before: Payload;
  beforeIsOriginal: boolean;
  outputType: ReviewCheckpoint["output_type"];
}) {
  const t = useTranslations();
  const { user } = useAppContext();
  const [open, setOpen] = useState(false);
  return (
    <li className="border-ax-border border-t py-1 first:border-t-0">
      <Collapsible
        isOpen={open}
        onOpenChange={setOpen}
        chevronPosition="start"
        trigger={
          <span className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
            <span className="text-ax-text font-medium">
              {t("flow_run_extras_history_revision", { revision: edit.revision })}
            </span>
            <span className="text-ax-text-secondary">
              {edit.cause === "corrections_folded"
                ? t("flow_run_extras_history_cause_corrections")
                : t("flow_run_extras_history_cause_edit")}
            </span>
            <span className="text-ax-text-secondary">{editorName(edit, user.id, t)}</span>
            <span className="text-ax-text-secondary">
              <ClientTime value={edit.created_at} format="date_time" />
            </span>
          </span>
        }
      >
        {open ? (
          <div className="grid grid-cols-1 gap-3 pt-2 lg:grid-cols-2">
            <div className="flex min-w-0 flex-col gap-1">
              <p className="text-ax-text text-sm font-medium">
                {beforeIsOriginal
                  ? t("flow_run_extras_history_original")
                  : t("flow_run_extras_history_before")}
              </p>
              <PayloadValue payload={before} outputType={outputType} />
            </div>
            <div className="flex min-w-0 flex-col gap-1">
              <p className="text-ax-text text-sm font-medium">
                {t("flow_run_extras_history_after")}
              </p>
              <PayloadValue payload={edit.payload_json} outputType={outputType} />
            </div>
          </div>
        ) : null}
      </Collapsible>
    </li>
  );
}

function HistoryList({ checkpoint }: { checkpoint: ReviewCheckpoint }) {
  const t = useTranslations();
  const history = useInfiniteQuery(reviewEditsQueryOptions(checkpoint));
  if (history.isPending)
    return <LoadingState rows={2} label={t("flow_run_extras_history_loading")} />;
  if (history.isError) {
    return (
      <ListError
        error={history.error}
        title={t("flow_run_extras_history_failed")}
        onRetry={() => void history.refetch()}
        isRetrying={history.isFetching}
      />
    );
  }
  const pages = history.data.pages;
  const baseline = pages[0]?.baseline ?? null;
  const edits = pages.flatMap((page) => page.items);
  if (edits.length === 0) {
    return <p className="text-ax-text-secondary text-sm">{t("flow_run_extras_history_empty")}</p>;
  }
  return (
    <div className="flex flex-col gap-2">
      <ol className="m-0 flex flex-col p-0" aria-label={t("flow_run_extras_history_heading")}>
        {edits.map((edit, index) => (
          <EditRow
            key={edit.id}
            edit={edit}
            // The first page's baseline is the step's original output (revision 1).
            before={index === 0 ? (baseline?.payload_json ?? null) : edits[index - 1]!.payload_json}
            beforeIsOriginal={index === 0 && baseline?.revision === 1}
            outputType={checkpoint.output_type}
          />
        ))}
      </ol>
      {history.hasNextPage ? (
        <div>
          <Button
            label={t("flow_run_extras_history_more")}
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

/**
 * Every change made to the paused step's output at this checkpoint, in
 * order: which revision, whether a reviewer edited it or transcript
 * corrections were folded in, who made it and when, and the output before
 * and after. Reading it is an audited evidence view, so it is read when
 * opened, for the revision the panel shows.
 */
export function ReviewHistory({ checkpoint }: { checkpoint: ReviewCheckpoint }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  return (
    <Collapsible
      isOpen={open}
      onOpenChange={setOpen}
      chevronPosition="start"
      trigger={<span className="text-sm font-medium">{t("flow_run_extras_history_heading")}</span>}
    >
      {open ? (
        <div className="pt-2">
          <HistoryList checkpoint={checkpoint} />
        </div>
      ) : null}
    </Collapsible>
  );
}
