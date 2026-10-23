"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import {
  failureFacts,
  reviewPolicySteps,
  type FailureFact,
  type ReviewPolicyStep
} from "./run-failure-facts";
import { runErrorCatalogText } from "./run-messages";
import { showRunStep } from "./run-steps";
import type { RunError, RunErrorWithGuidance } from "./runs-api";

type Translate = ReturnType<typeof useTranslations>;

/** A run error, with the error taxonomy's guidance when the run detail carried it. */
type FailureError = RunError &
  Partial<Pick<RunErrorWithGuidance, "user_action" | "consumer_action">>;

function FactLine({
  fact,
  t,
  stepName
}: {
  fact: FailureFact;
  t: Translate;
  stepName?: (order: number) => string | null;
}) {
  switch (fact.kind) {
    case "stopped_at": {
      const name = fact.name ?? stepName?.(fact.order) ?? null;
      return (
        <li>
          <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              {name
                ? t("flow_run_extras_failure_stopped_at", { order: fact.order, name })
                : t("flow_run_extras_failure_stopped_at_unnamed", { order: fact.order })}
            </span>
            <Button
              label={t("flow_run_show_failed_step")}
              size="sm"
              variant="secondary"
              onClick={() => showRunStep(fact.order)}
            />
          </span>
        </li>
      );
    }
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

/** The steps a refused review policy concerns, each as a step name. */
function ReviewPolicyStepList({
  error,
  steps
}: {
  error: FailureError;
  steps: readonly ReviewPolicyStep[];
}) {
  const t = useTranslations();
  const affected = reviewPolicySteps(error, steps);
  if (affected.steps.length === 0) return null;
  const heading = affected.exact
    ? t("flow_run_error_affected_step")
    : t("flow_run_error_possible_affected_steps");
  return (
    <div className="flex flex-col gap-1">
      <p className="text-ax-text m-0 text-sm font-medium">{heading}</p>
      <ul aria-label={heading} className="m-0 flex flex-wrap gap-1.5 p-0">
        {affected.steps.map((step) => (
          <li
            key={step.order}
            className="border-ax-border rounded-ax-inner text-ax-text list-none border px-2 py-0.5 text-sm break-words"
          >
            {step.name
              ? t("flow_run_error_step_label_with_name", { step: step.order, name: step.name })
              : t("flow_run_error_step_label", { step: step.order })}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Why a run failed and what to do about it: the catalog's sentence for its
 * error code (the error taxonomy's guidance, in English, when the catalog
 * has none), then the facts the error carries (where it stopped, with a
 * way to the step, what a timed-out step was doing, whether a provider or
 * a tool may already have acted, what a tool said, whether running again
 * unchanged can help). A refused review policy, which keeps the run from
 * starting, names the steps it concerns. The error's code, technical
 * message and the guidance for API clients are there for support, behind
 * a disclosure that renders them only when opened.
 */
export function RunFailure({
  error,
  stepName,
  reviewSteps = []
}: {
  error: FailureError;
  /** The step's label in the run's version, for the facts that name a step. */
  stepName?: (order: number) => string | null;
  /** The flow's steps, for a refused review policy that names no step. */
  reviewSteps?: readonly ReviewPolicyStep[];
}) {
  const t = useTranslations();
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const reviewPolicy = error.code === "flow_review_policy_invalid";
  const catalog = runErrorCatalogText(error, t);
  const guidance = catalog ? null : (error.user_action?.trim() ?? null);
  return (
    <Banner
      status="error"
      title={reviewPolicy ? t("flow_run_error_not_started") : t("flow_runs_failed_title")}
      description={
        reviewPolicy
          ? t("flow_run_error_review_policy_invalid_summary")
          : (catalog ?? (guidance ? undefined : t("flow_runs_error_unknown")))
      }
      collapsible={false}
    >
      <div className="flex flex-col gap-3">
        {guidance ? (
          <p lang="en" className="text-ax-text m-0 text-sm">
            {guidance}
          </p>
        ) : null}
        {reviewPolicy ? (
          <>
            <p className="text-ax-text m-0 text-sm">
              {t("flow_run_error_review_policy_invalid_action")}
            </p>
            <ReviewPolicyStepList error={error} steps={reviewSteps} />
          </>
        ) : (
          <ul className="text-ax-text m-0 flex list-disc flex-col gap-1 pl-5 text-sm">
            {failureFacts(error).map((fact) => (
              <FactLine key={fact.kind} fact={fact} t={t} stepName={stepName} />
            ))}
          </ul>
        )}
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
              {error.consumer_action ? (
                <>
                  <dt className="text-ax-text-secondary">
                    {t("flow_run_journey_failure_consumer_action")}
                  </dt>
                  <dd lang="en" className="text-ax-text m-0 break-words">
                    {error.consumer_action}
                  </dd>
                </>
              ) : null}
            </dl>
          ) : null}
        </Collapsible>
      </div>
    </Banner>
  );
}
