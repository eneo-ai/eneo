"use client";

import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { approveOnly } from "./review-extras-api";
import { runKeys, type ReviewCheckpoint } from "./runs-api";

/**
 * Approves the paused step's output as it is saved without letting the run
 * go on: the decision is recorded now and the run waits until someone
 * resumes it (the panel then offers "continue"). Offered for the saved
 * output only; a correction is saved first. Refusals go to the panel, which
 * shows them where they belong and reads a checkpoint someone else changed
 * again.
 */
export function ReviewApproveOnly({
  checkpoint,
  isBlocked,
  onRefused,
  mayApprove = () => true
}: {
  checkpoint: ReviewCheckpoint;
  /** Another decision on this checkpoint is on its way. */
  isBlocked: boolean;
  onRefused: (error: unknown) => void;
  /** Asked on each press: false when the panel holds approval and says why. */
  mayApprove?: () => boolean | Promise<boolean>;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const approve = useMutation({
    mutationFn: () => approveOnly(checkpoint),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: runKeys.run(checkpoint.flow_id, checkpoint.flow_run_id)
      });
      announce(t("flow_run_extras_review_approved_only"));
    },
    onError: onRefused
  });
  return (
    <Button
      label={t("flow_run_extras_review_approve_only")}
      isLoading={approve.isPending}
      isInterruptible
      onClick={() => {
        if (isBlocked || approve.isPending) return;
        void Promise.resolve(mayApprove()).then((may) => {
          if (may) approve.mutate();
        });
      }}
    />
  );
}
