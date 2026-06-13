"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
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
    <Dialog open={pending !== null} onOpenChange={(open) => !open && onCancel()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("governance_confirm_title")}</DialogTitle>
          <DialogDescription>{t("governance_confirm_desc")}</DialogDescription>
        </DialogHeader>
        <ul className="list-disc space-y-1 pl-6 text-sm">
          {(pending ?? []).map((key) => (
            <li key={key}>{t(key)}</li>
          ))}
        </ul>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={saving}>
            {t("cancel")}
          </Button>
          <Button onClick={onConfirm} disabled={saving} aria-busy={saving}>
            {saving ? t("governance_saving") : t("governance_confirm_and_save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
