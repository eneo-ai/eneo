"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useRef, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EneoApiError } from "@/lib/api/errors";
import { refusalText } from "./run-messages";
import { runHref } from "./run-routes";
import { startedByUser } from "./run-starter";
import { isCancellable, runStatusView } from "./run-status";
import {
  cancelRun,
  newIdempotencyKey,
  retryRun,
  runKeys,
  type RunRetry,
  type RunSummary
} from "./runs-api";

/**
 * Retry from the failed step and cancel, wherever a run is shown (its page,
 * a row of the runs list): the same rules for when each is offered, the same
 * requests and confirmation, and the same words for what came of it. Each
 * place decides only where those words show (a notice, a toast).
 */

/** What came of an action, for the place that shows it. */
export type RunActionNotice = {
  status: "error" | "warning" | "info" | "success";
  title: string;
  description?: string;
  /** A page the notice points to, offered as a link beside it. */
  link?: { label: string; href: string };
};

/** Why a failed run cannot be retried by this person now. */
export type RetryHeldBack = "version_changed" | "starter_only";

/**
 * Which actions a run offers the person: retry needs the right to run
 * flows, a failed run of the version published now, and (when the core
 * names the starter) the person who started it; cancel follows the core's
 * status table.
 */
export function runActions(
  run: Pick<RunSummary, "status" | "flow_version" | "started_by">,
  person: { canRun: boolean; userId: string; publishedVersion: number | null | undefined }
): { retry: boolean; retryHeldBack: RetryHeldBack | null; cancel: boolean } {
  const failed = person.canRun && run.status === "failed";
  const currentVersion = run.flow_version === person.publishedVersion;
  const otherStarter = startedByUser(run, person.userId) === false;
  const retryHeldBack: RetryHeldBack | null = !failed
    ? null
    : !currentVersion
      ? "version_changed"
      : otherStarter
        ? "starter_only"
        : null;
  return {
    retry: failed && retryHeldBack === null,
    retryHeldBack,
    cancel: isCancellable(run.status)
  };
}

/**
 * Retries a failed run from its failed step and opens the new run's page.
 * One key per retry of the run, so a lost response replays the same new run.
 * When the core answers with a retry started earlier (nothing new started),
 * the person is told so, with a link to that run, instead of being taken
 * there unawares.
 */
export function useRetryRun(
  run: { spaceRouteId: string; flowId: string; runId: string },
  report: (notice: RunActionNotice) => void
) {
  const { spaceRouteId, flowId, runId } = run;
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const router = useRouter();
  const retryKey = useRef<string | null>(null);
  return useMutation({
    mutationFn: () => {
      retryKey.current ??= newIdempotencyKey();
      return retryRun(flowId, runId, retryKey.current);
    },
    onSuccess: (child: RunRetry) => {
      void queryClient.invalidateQueries({ queryKey: runKeys.list(flowId) });
      const href = runHref(spaceRouteId, flowId, child.run.id);
      if (!child.created) {
        report({
          status: "info",
          title: t("flow_runs_retry_replayed"),
          link: { label: t("flow_runs_retry_replayed_open"), href }
        });
        return;
      }
      announce(t("flow_runs_retry_started", { order: child.first_executed_step_order }));
      router.push(href);
    },
    onError: (error) => {
      if (error instanceof EneoApiError && error.reason === "flow_run_idempotency_conflict") {
        retryKey.current = null;
      }
      report({
        status: "error",
        title: t("flow_runs_retry_failed"),
        description: refusalText(error, t)
      });
    }
  });
}

/** "Kör om från steget som misslyckades", for a run `runActions` offers it for. */
export function RetryRunButton({
  spaceRouteId,
  flowId,
  runId,
  report,
  size,
  variant
}: {
  spaceRouteId: string;
  flowId: string;
  runId: string;
  report: (notice: RunActionNotice) => void;
  size?: "sm" | "md";
  variant?: "primary" | "secondary";
}) {
  const t = useTranslations();
  const retry = useRetryRun({ spaceRouteId, flowId, runId }, report);
  return (
    <Button
      label={t("flow_runs_retry")}
      size={size}
      variant={variant}
      onClick={() => {
        if (!retry.isPending) retry.mutate();
      }}
      isLoading={retry.isPending}
      isInterruptible
    />
  );
}

/**
 * Cancels a run after a confirmation that says what cancelling cannot undo.
 * A run that had already ended comes back unchanged, and the person hears so.
 */
export function CancelRunButton({
  flowId,
  runId,
  report,
  onCancelled,
  size
}: {
  flowId: string;
  runId: string;
  report: (notice: RunActionNotice) => void;
  /**
   * The run is cancelled and read again, so this button and its dialog go:
   * the place that shows the run moves focus on (`useFocusRescue`).
   */
  onCancelled: () => void;
  size?: "sm" | "md";
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const cancel = useMutation({
    mutationFn: () => cancelRun(flowId, runId),
    onSuccess: async (run) => {
      const reread = Promise.all([
        queryClient.invalidateQueries({ queryKey: runKeys.run(flowId, runId) }),
        queryClient.invalidateQueries({ queryKey: runKeys.list(flowId) })
      ]);
      if (run.status === "cancelled") {
        announce(t("flow_runs_cancel_done"));
        // The dialog stays open until the run reads as cancelled and this
        // button goes with it: closing it first would return focus to a
        // button about to go.
        await reread;
        onCancelled();
        return;
      }
      setConfirming(false);
      report({
        status: "info",
        title: t("flow_runs_cancel_already_ended", {
          status: t(runStatusView(run.status).labelKey)
        })
      });
    },
    onError: (error) => {
      setConfirming(false);
      report({
        status: "error",
        title: t("flow_runs_cancel_failed"),
        description: refusalText(error, t)
      });
    }
  });
  return (
    <>
      <Button
        label={t("flow_runs_cancel")}
        variant="destructive"
        size={size}
        onClick={() => setConfirming(true)}
        isLoading={cancel.isPending}
        isInterruptible
      />
      <ConfirmDialogControlled
        open={confirming}
        onOpenChange={(open) => {
          if (!cancel.isPending) setConfirming(open);
        }}
        title={t("flow_runs_cancel_title")}
        description={t("flow_runs_cancel_description")}
        confirmLabel={t("flow_runs_cancel")}
        pending={cancel.isPending}
        onConfirm={() => cancel.mutate()}
      />
    </>
  );
}
