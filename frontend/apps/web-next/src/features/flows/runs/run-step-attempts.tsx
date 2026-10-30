"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { StepAttemptList } from "./run-trace-attempts";
import { runEvidenceQueryOptions } from "./runs-api";

/**
 * The attempts one step made, inside its card: closed until asked for, since
 * they come with the run's evidence (an audited read, shared with the trace,
 * so one read serves both). Offered only to a caller the core lets read the
 * evidence.
 */
export function StepAttempts({
  flowId,
  runId,
  order,
  title,
  runSettled
}: {
  flowId: string;
  runId: string;
  order: number;
  title: string;
  /** The run has ended (`isTerminal`). */
  runSettled: boolean;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const evidence = useQuery({
    ...runEvidenceQueryOptions(flowId, runId, runSettled),
    enabled: open
  });
  const attempts = (evidence.data?.step_attempts ?? []).filter(
    (attempt) => attempt.step_order === order
  );
  return (
    <Collapsible
      isOpen={open}
      onOpenChange={setOpen}
      chevronPosition="start"
      trigger={<span className="text-sm font-medium">{t("flow_run_more_attempts")}</span>}
    >
      {open ? (
        <div className="pt-2">
          {evidence.isPending ? (
            <LoadingState rows={2} label={t("flow_run_more_attempts_loading")} />
          ) : evidence.isError ? (
            <ListError
              error={evidence.error}
              title={t("flow_run_more_attempts_failed")}
              onRetry={() => void evidence.refetch()}
              isRetrying={evidence.isFetching}
            />
          ) : attempts.length === 0 ? (
            <p className="text-ax-text-secondary m-0 text-sm">{t("flow_run_more_attempts_none")}</p>
          ) : (
            <StepAttemptList
              attempts={attempts}
              label={t("flow_run_more_attempts_of", { step: title })}
            />
          )}
        </div>
      ) : null}
    </Collapsible>
  );
}
