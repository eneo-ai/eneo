"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { QuietBanner } from "@/components/astryx/banner";
import { failureFacts, type FailureFact } from "./run-failure-facts";
import { runErrorText } from "./run-messages";
import type { RunError } from "./runs-api";

type Translate = ReturnType<typeof useTranslations>;

function FactLine({ fact, t }: { fact: FailureFact; t: Translate }) {
  switch (fact.kind) {
    case "stopped_at":
      return (
        <li>
          {fact.name
            ? t("flow_run_extras_failure_stopped_at", { order: fact.order, name: fact.name })
            : t("flow_run_extras_failure_stopped_at_unnamed", { order: fact.order })}
        </li>
      );
    case "phase":
      return (
        <li>
          {t("flow_run_extras_failure_phase", {
            phase: t(`flow_run_extras_phase_${fact.phase}`)
          })}
        </li>
      );
    case "progress":
      return (
        <li>
          {t("flow_run_extras_failure_progress", {
            completed: fact.completed,
            total: fact.total
          })}
        </li>
      );
    case "provider_may_have_finished":
      return <li>{t("flow_run_extras_failure_provider_unknown")}</li>;
    case "tool_may_have_acted":
      return <li>{t("flow_run_extras_failure_tool_may_have_acted")}</li>;
    case "tool_said":
      return (
        <li>
          {t("flow_run_extras_failure_tool_said")}{" "}
          <q className="break-words whitespace-pre-wrap">{fact.text}</q>
        </li>
      );
    case "service_said":
      return (
        <li>
          {t("flow_run_extras_failure_service_said")}{" "}
          <q className="break-words whitespace-pre-wrap">{fact.text}</q>
        </li>
      );
    case "retry":
      return (
        <li>
          {fact.retryable
            ? t("flow_run_extras_failure_retryable")
            : t("flow_run_extras_failure_not_retryable")}
        </li>
      );
  }
}

/**
 * Why a run failed and what to do about it: the catalog's sentence for its
 * error code, then the facts the error carries (where it stopped, what a
 * timed-out step was doing, whether a provider or a tool may already have
 * acted, what a tool said, whether running again unchanged can help). The
 * error's code and technical message are there for support, behind a
 * disclosure that renders them only when opened.
 */
export function RunFailure({ error }: { error: RunError }) {
  const t = useTranslations();
  const [technicalOpen, setTechnicalOpen] = useState(false);
  return (
    <QuietBanner
      status="error"
      title={t("flow_runs_failed_title")}
      description={runErrorText(error, t)}
      collapsible={false}
    >
      <div className="flex flex-col gap-3">
        <ul className="text-ax-text m-0 flex list-disc flex-col gap-1 pl-5 text-sm">
          {failureFacts(error).map((fact) => (
            <FactLine key={fact.kind} fact={fact} t={t} />
          ))}
        </ul>
        <Collapsible
          isOpen={technicalOpen}
          onOpenChange={setTechnicalOpen}
          chevronPosition="start"
          trigger={
            <span className="text-sm font-medium">{t("flow_run_extras_failure_technical")}</span>
          }
        >
          {technicalOpen ? (
            <dl className="grid grid-cols-1 gap-x-4 gap-y-1 pt-2 text-sm sm:grid-cols-[max-content_1fr]">
              <dt className="text-ax-text-secondary">{t("flow_run_extras_failure_code")}</dt>
              <dd className="text-ax-text m-0 font-mono break-all">{error.code}</dd>
              <dt className="text-ax-text-secondary">{t("flow_run_extras_failure_message")}</dt>
              <dd className="text-ax-text m-0 break-words whitespace-pre-wrap">{error.message}</dd>
            </dl>
          ) : null}
        </Collapsible>
      </div>
    </QuietBanner>
  );
}
