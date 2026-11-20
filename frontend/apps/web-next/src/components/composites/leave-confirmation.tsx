import { useTranslations } from "use-intl";
import { useImperativeHandle, useState, type Ref } from "react";
import { useLeaveConfirmation } from "@/lib/navigation";
import { ConfirmDialogControlled } from "./confirm-dialog";

export type LeaveConfirmationHandle = {
  confirm(action: () => void, onStay?: () => void): void;
};

/** Shares the unsaved-edit decision across manual-save editors. */
export function LeaveConfirmation({
  active,
  ref,
  onLeave,
  onStay,
  title,
  description,
  confirmLabel
}: {
  active: boolean;
  ref?: Ref<LeaveConfirmationHandle>;
  onLeave?: () => void;
  /** The user chose to stay: an editor whose control behind the dialog is gone can place focus. */
  onStay?: () => void;
  title?: string;
  description?: string;
  confirmLabel?: string;
}) {
  const t = useTranslations();
  const { blocked, leave, stay } = useLeaveConfirmation(active, onLeave);
  const [pending, setPending] = useState<{ action: () => void; onStay?: () => void } | null>(null);
  useImperativeHandle(ref, () => ({
    confirm(action, afterStay) {
      if (active) setPending({ action, onStay: afterStay });
      else action();
    }
  }));
  return (
    <ConfirmDialogControlled
      open={blocked || pending !== null}
      onOpenChange={(open) => {
        if (!open) {
          setPending(null);
          stay();
          pending?.onStay?.();
          onStay?.();
        }
      }}
      title={title ?? t("unsaved_navigation_title")}
      description={description ?? t("unsaved_navigation_description")}
      confirmLabel={confirmLabel ?? t("unsaved_navigation_leave")}
      onConfirm={() => {
        setPending(null);
        if (blocked) leave();
        else if (pending) {
          onLeave?.();
          pending.action();
        }
      }}
    />
  );
}
