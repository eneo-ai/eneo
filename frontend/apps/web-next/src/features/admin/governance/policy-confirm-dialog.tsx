"use client";

import { useTranslations } from "next-intl";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import type { ConfirmKey } from "./policy-draft";

export function PolicyConfirmDialog({
  pending,
  saving,
  onCancel,
  onConfirm
}: {
  /** Translation keys for the risky changes about to be applied; null = closed. */
  pending: ConfirmKey[] | null;
  saving: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useTranslations();

  return (
    <ConfirmDialogControlled
      open={pending !== null}
      onOpenChange={(open) => !open && onCancel()}
      title={t("governance_confirm_title")}
      description={t("governance_confirm_desc")}
      confirmLabel={saving ? t("governance_saving") : t("governance_confirm_and_save")}
      variant="default"
      pending={saving}
      onConfirm={onConfirm}
    >
      <ul className="list-disc space-y-1 pl-6 text-sm">
        {(pending ?? []).map((key) => (
          <li key={key}>{t(key)}</li>
        ))}
      </ul>
    </ConfirmDialogControlled>
  );
}
