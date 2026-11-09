import { Button } from "@astryxdesign/core/Button";
import { proportional, type TableColumn } from "@astryxdesign/core/Table";
import { useMutation } from "@tanstack/react-query";
import { useLocale, useTranslations } from "use-intl";
import { useRef, useState } from "react";
import { Table } from "@/components/astryx/table";
import { ClientTime } from "@/components/composites/client-time";
import { ListError } from "@/components/composites/query-state";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";
import { formatCount } from "./run-format";
import { tokenTotal } from "./run-progress";
import { getProviderCalls, type ProviderCall, type ProviderCallPage } from "./run-trace-api";

type Row = ProviderCall & Record<string, unknown>;

/**
 * A column's share of the table, with a floor in step with it: a share's
 * floor sets the table's least width in proportion (the default 120 px floor
 * made a share of one 1440 px wide), so these twelve shares need 768 px.
 */
const UNIT = 64;
const share = (weight: number) => proportional(weight, { minWidth: weight * UNIT });
/** The room the table's columns need; with less, the calls stack. */
const CALLS_TABLE_WIDTH = 12 * UNIT;

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

function CallStatus({ call }: { call: ProviderCall }) {
  const t = useTranslations();
  const view = STATUS_VIEWS[call.status] ?? STATUS_VIEWS.started;
  return <StatusLabel status={view.tone} label={t(view.labelKey)} />;
}

/**
 * The calls the run made to its AI services, in the core's order (step,
 * attempt, call): what kind of call, the model asked for and the one that
 * answered, how each ended (an outcome the runtime cannot prove is said so),
 * and the tokens used. A table where its six columns fit; a phone, or a
 * narrower place (an upright iPad beside the menu), lists each call as a row
 * of its own. The trace carries the first
 * page; each further page is its own audited read, asked for with "show more".
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
  const phone = usePhoneScreen();
  const rootRef = useRef<HTMLDivElement>(null);
  const narrow = useElementWidth(rootRef, (width) => width < CALLS_TABLE_WIDTH) ?? false;
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

  const stepAttempt = (call: ProviderCall) =>
    t("flow_run_extras_call_step_attempt", {
      step: stepName(call.step_order),
      attempt: call.attempt_no
    });
  const model = (call: ProviderCall) => call.response_model ?? call.requested_model;
  const columns: TableColumn<Row>[] = [
    {
      key: "step",
      header: t("flow_run_extras_call_step"),
      width: share(3),
      renderCell: stepAttempt
    },
    {
      key: "kind",
      header: t("flow_run_extras_call_kind"),
      width: share(2),
      renderCell: (call) => callKind(call, t)
    },
    {
      key: "model",
      header: t("flow_run_extras_call_model"),
      width: share(2),
      renderCell: (call) => <span className="break-words">{model(call)}</span>
    },
    {
      key: "status",
      header: t("flow_run_extras_call_status"),
      width: share(2),
      renderCell: (call) => <CallStatus call={call} />
    },
    {
      key: "tokens",
      header: t("flow_run_extras_call_tokens"),
      width: share(1),
      renderCell: (call) => {
        const total = tokenTotal(call.num_tokens_input, call.num_tokens_output);
        return total === null ? "–" : formatCount(total, locale);
      }
    },
    {
      key: "requested",
      header: t("flow_run_extras_call_requested"),
      width: share(2),
      renderCell: (call) => <ClientTime value={call.requested_at} format="date_time" />
    }
  ];

  return (
    <div ref={rootRef} className="flex flex-col gap-2">
      <p className="text-ax-text-secondary text-sm">
        {t("flow_run_extras_calls_count", {
          shown: formatCount(items.length, locale),
          total: `${formatCount(last.total_count, locale)}${last.total_count_truncated ? "+" : ""}`
        })}
      </p>
      {phone || narrow ? (
        <ul
          aria-label={t("flow_run_extras_calls_heading")}
          className="m-0 flex list-none flex-col p-0"
        >
          {items.map((call) => {
            const tokens = tokenTotal(call.num_tokens_input, call.num_tokens_output);
            return (
              <li
                key={call.event_id}
                className="border-ax-border flex flex-col items-start gap-1 border-b py-3 first:pt-0 last:border-b-0"
              >
                <span className="text-ax-text text-sm font-medium">{stepAttempt(call)}</span>
                <span className="text-ax-text-secondary text-sm [overflow-wrap:anywhere]">
                  {callKind(call, t)} · {model(call)}
                </span>
                <span className="text-ax-text-secondary flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                  <CallStatus call={call} />
                  {tokens ? (
                    <span>{t("flow_runs_tokens", { count: formatCount(tokens, locale) })}</span>
                  ) : null}
                  <ClientTime value={call.requested_at} format="date_time" />
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <Table<Row>
          data={items as Row[]}
          columns={columns}
          idKey="event_id"
          aria-label={t("flow_run_extras_calls_heading")}
        />
      )}
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
