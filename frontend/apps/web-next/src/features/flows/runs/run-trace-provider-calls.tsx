"use client";

import { Button } from "@astryxdesign/core/Button";
import { proportional, type TableColumn } from "@astryxdesign/core/Table";
import { useMutation } from "@tanstack/react-query";
import { useLocale, useTranslations } from "use-intl";
import { useState } from "react";
import { Table } from "@/components/astryx/table";
import { ClientTime } from "@/components/composites/client-time";
import { ListError } from "@/components/composites/query-state";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { formatCount } from "./run-format";
import { tokenTotal } from "./run-progress";
import { getProviderCalls, type ProviderCall, type ProviderCallPage } from "./run-trace-api";

type Row = ProviderCall & Record<string, unknown>;

const STATUS_VIEWS: Record<ProviderCall["status"], { tone: StatusTone; labelKey: string }> = {
  started: { tone: "accent", labelKey: "flow_run_extras_call_started" },
  completed: { tone: "success", labelKey: "flow_run_extras_call_completed" },
  rejected: { tone: "error", labelKey: "flow_run_extras_call_rejected" },
  outcome_unknown: { tone: "warning", labelKey: "flow_run_extras_call_outcome_unknown" }
};

function callKind(call: ProviderCall, t: ReturnType<typeof useTranslations>): string {
  const kind =
    call.call_kind === "transcription"
      ? t("flow_run_extras_call_kind_transcription")
      : t("flow_run_extras_call_kind_completion");
  if (call.call_reason === "tool_round") return `${kind} · ${t("flow_run_extras_call_tool_round")}`;
  if (call.call_reason === "response_format_fallback") {
    return `${kind} · ${t("flow_run_extras_call_format_fallback")}`;
  }
  return kind;
}

/**
 * The calls the run made to its AI services, in the core's order (step,
 * attempt, call): what kind of call, the model asked for and the one that
 * answered, how each ended (an outcome the runtime cannot prove is said so),
 * and the tokens used. The trace carries the first page; each further page
 * is its own audited read, asked for with "show more".
 */
export function RunTraceProviderCalls({
  flowId,
  runId,
  firstPage,
  stepName
}: {
  flowId: string;
  runId: string;
  firstPage: ProviderCallPage;
  stepName: (order: number) => string;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const [pages, setPages] = useState<ProviderCallPage[]>([]);
  const more = useMutation({
    mutationFn: (after: string) => getProviderCalls(flowId, runId, after),
    onSuccess: (page) => setPages((loaded) => [...loaded, page])
  });
  const last = pages.at(-1) ?? firstPage;
  const items = [firstPage, ...pages].flatMap((page) => page.items);

  if (items.length === 0) {
    return <p className="text-ax-text-secondary text-sm">{t("flow_run_extras_calls_none")}</p>;
  }

  const columns: TableColumn<Row>[] = [
    {
      key: "step",
      header: t("flow_run_extras_call_step"),
      width: proportional(3),
      renderCell: (call) =>
        t("flow_run_extras_call_step_attempt", {
          step: stepName(call.step_order),
          attempt: call.attempt_no
        })
    },
    {
      key: "kind",
      header: t("flow_run_extras_call_kind"),
      width: proportional(2),
      renderCell: (call) => callKind(call, t)
    },
    {
      key: "model",
      header: t("flow_run_extras_call_model"),
      width: proportional(2),
      renderCell: (call) => (
        <span className="break-words">{call.response_model ?? call.requested_model}</span>
      )
    },
    {
      key: "status",
      header: t("flow_run_extras_call_status"),
      width: proportional(2),
      renderCell: (call) => {
        const view = STATUS_VIEWS[call.status] ?? STATUS_VIEWS.started;
        return <StatusLabel status={view.tone} label={t(view.labelKey)} />;
      }
    },
    {
      key: "tokens",
      header: t("flow_run_extras_call_tokens"),
      width: proportional(1),
      renderCell: (call) => {
        const total = tokenTotal(call.num_tokens_input, call.num_tokens_output);
        return total === null ? "–" : formatCount(total, locale);
      }
    },
    {
      key: "requested",
      header: t("flow_run_extras_call_requested"),
      width: proportional(2),
      renderCell: (call) => <ClientTime value={call.requested_at} format="date_time" />
    }
  ];

  return (
    <div className="flex flex-col gap-2">
      <p className="text-ax-text-secondary text-sm">
        {t("flow_run_extras_calls_count", {
          shown: formatCount(items.length, locale),
          total: `${formatCount(last.total_count, locale)}${last.total_count_truncated ? "+" : ""}`
        })}
      </p>
      <Table<Row>
        data={items as Row[]}
        columns={columns}
        idKey="event_id"
        aria-label={t("flow_run_extras_calls_heading")}
        className="min-w-[48rem]"
      />
      {more.isError ? (
        <ListError
          error={more.error}
          title={t("flow_run_extras_calls_more_failed")}
          onRetry={() => {
            if (last.next_after_event_id) more.mutate(last.next_after_event_id);
          }}
          isRetrying={more.isPending}
        />
      ) : null}
      {last.has_more && last.next_after_event_id ? (
        <div>
          <Button
            label={t("flow_run_extras_calls_more")}
            isLoading={more.isPending}
            isInterruptible
            onClick={() => {
              if (!more.isPending && last.next_after_event_id) {
                more.mutate(last.next_after_event_id);
              }
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
