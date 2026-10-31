"use client";

import { useTranslations } from "use-intl";
import { useLeaveConfirmation } from "@/lib/navigation";
import { ConfirmDialogControlled } from "./confirm-dialog";

/** Shares the unsaved-edit decision across manual-save editors. */
export function LeaveConfirmation({
  active,
  onLeave,
  title,
  description,
  confirmLabel
}: {
  active: boolean;
  onLeave?: () => void;
  title?: string;
  description?: string;
  confirmLabel?: string;
}) {
  const t = useTranslations();
  const { blocked, leave, stay } = useLeaveConfirmation(active, onLeave);
  return (
    <ConfirmDialogControlled
      open={blocked}
      onOpenChange={(open) => {
        if (!open) stay();
      }}
      title={title ?? t("unsaved_navigation_title")}
      description={description ?? t("unsaved_navigation_description")}
      confirmLabel={confirmLabel ?? t("unsaved_navigation_leave")}
      onConfirm={leave}
    />
  );
}
