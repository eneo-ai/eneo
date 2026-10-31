"use client";

import { useTranslations } from "use-intl";
import { useImperativeHandle, useState, type Ref } from "react";
import { useLeaveConfirmation } from "@/lib/navigation";
import { ConfirmDialogControlled } from "./confirm-dialog";

export type LeaveConfirmationHandle = { confirm(action: () => void): void };

/** Shares the unsaved-edit decision across manual-save editors. */
export function LeaveConfirmation({
  active,
  ref,
  onLeave,
  title,
  description,
  confirmLabel
}: {
  active: boolean;
  ref?: Ref<LeaveConfirmationHandle>;
  onLeave?: () => void;
  title?: string;
  description?: string;
  confirmLabel?: string;
}) {
  const t = useTranslations();
  const { blocked, leave, stay } = useLeaveConfirmation(active, onLeave);
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null);
  useImperativeHandle(ref, () => ({
    confirm(action) {
      if (active) setPendingAction(() => action);
      else action();
    }
  }));
  return (
    <ConfirmDialogControlled
      open={blocked || pendingAction !== null}
      onOpenChange={(open) => {
        if (!open) {
          setPendingAction(null);
          stay();
        }
      }}
      title={title ?? t("unsaved_navigation_title")}
      description={description ?? t("unsaved_navigation_description")}
      confirmLabel={confirmLabel ?? t("unsaved_navigation_leave")}
      onConfirm={() => {
        setPendingAction(null);
        if (blocked) leave();
        else if (pendingAction) {
          onLeave?.();
          pendingAction();
        }
      }}
    />
  );
}
