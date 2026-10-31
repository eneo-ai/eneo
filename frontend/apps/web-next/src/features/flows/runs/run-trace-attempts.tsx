"use client";

import { useLocale, useTranslations } from "use-intl";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useState } from "react";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import type { Schema } from "@/lib/api/models";
import { formatCount, formatSeconds } from "./run-format";
import { runErrorText } from "./run-messages";
import { tokenTotal } from "./run-progress";
import { attemptDurationMs, attemptsByStep } from "./run-trace-rules";
import { CopyButton } from "./run-copy";
import { JsonValue } from "./run-json";

type Attempt = Schema<"FlowStepAttemptPublic">;

const ATTEMPT_VIEWS: Record<Attempt["status"], { tone: StatusTone; labelKey: string }> = {
  started: { tone: "accent", labelKey: "flow_run_extras_attempt_started" },
  completed: { tone: "success", labelKey: "flow_run_extras_attempt_completed" },
  failed: { tone: "error", labelKey: "flow_run_extras_attempt_failed" },
  cancelled: { tone: "neutral", labelKey: "flow_run_extras_attempt_cancelled" }
};

function AttemptRow({ attempt }: { attempt: Attempt }) {
  const t = useTranslations();
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const view = ATTEMPT_VIEWS[attempt.status] ?? ATTEMPT_VIEWS.started;
  const duration = attemptDurationMs(attempt);
  const tokens = tokenTotal(attempt.num_tokens_input, attempt.num_tokens_output);
  const model = attempt.response_model?.trim() || attempt.requested_model?.trim();
  const facts = [
    duration !== null
      ? t("flow_runs_step_took", { time: formatSeconds(duration / 1000, t) })
      : null,
    model ? t("flow_run_extras_attempt_model", { model }) : null,
    tokens !== null
      ? t("flow_run_journey_step_tokens", {
          total: formatCount(tokens, locale),
          input:
            attempt.num_tokens_input == null ? "–" : formatCount(attempt.num_tokens_input, locale),
          output:
            attempt.num_tokens_output == null ? "–" : formatCount(attempt.num_tokens_output, locale)
        }) +
        (attempt.num_tokens_input == null || attempt.num_tokens_output == null
          ? ` ${t("flow_runs_usage_incomplete")}`
          : "")
      : attempt.status !== "started"
        ? t("flow_run_token_usage_not_recorded")
        : null,
    attempt.finish_reason?.trim()
      ? t("flow_run_extras_attempt_finish_reason", { reason: attempt.finish_reason.trim() })
      : null
  ].filter(Boolean);
  return (
    <li className="border-ax-border flex flex-col gap-1 border-t py-2 first:border-t-0">
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-ax-text text-sm font-medium">
          {t("flow_run_extras_attempt_number", { number: attempt.attempt_no })}
        </span>
        <StatusLabel status={view.tone} label={t(view.labelKey)} />
      </span>
      {facts.length > 0 ? (
        <span className="text-ax-text-secondary text-xs">{facts.join(" · ")}</span>
      ) : null}
      {attempt.status === "failed" && attempt.error_code ? (
        <span className="text-ax-text text-sm">
          {runErrorText({ code: attempt.error_code, details: null }, t)}
        </span>
      ) : null}
      <Collapsible
        isOpen={open}
        onOpenChange={setOpen}
        chevronPosition="start"
        trigger={t("flow_run_extras_attempt_details", { number: attempt.attempt_no })}
      >
        {open ? (
          <div className="flex min-w-0 flex-col gap-2 pt-2">
            <div className="flex justify-end">
              <CopyButton
                label={t("flow_run_extras_attempt_copy", { number: attempt.attempt_no })}
                value={attempt}
              />
            </div>
            <JsonValue value={attempt} />
          </div>
        ) : null}
      </Collapsible>
    </li>
  );
}

/**
 * The attempts one step made, in order: how each ended, how long it took,
 * the model that answered, the tokens it used and why the model stopped.
 */
export function StepAttemptList({
  attempts,
  label
}: {
  attempts: readonly Attempt[];
  label: string;
}) {
  return (
    <ol className="m-0 flex flex-col p-0" aria-label={label}>
      {attempts.map((attempt) => (
        <AttemptRow key={attempt.id} attempt={attempt} />
      ))}
    </ol>
  );
}

/**
 * Every attempt each step made in this run, in order. A step tried more
 * than once shows each try.
 */
export function RunTraceAttempts({
  attempts,
  stepName
}: {
  attempts: readonly Attempt[];
  stepName: (order: number) => string;
}) {
  const t = useTranslations();
  const grouped = [...attemptsByStep(attempts)];
  if (grouped.length === 0) {
    return <p className="text-ax-text-secondary text-sm">{t("flow_run_extras_attempts_none")}</p>;
  }
  return (
    <div className="flex flex-col gap-4">
      {grouped.map(([order, items]) => (
        <div key={order} className="flex flex-col gap-1">
          <h4 className="text-ax-text text-sm font-semibold">{stepName(order)}</h4>
          <StepAttemptList attempts={items} label={stepName(order)} />
        </div>
      ))}
    </div>
  );
}
