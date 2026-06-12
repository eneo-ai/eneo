"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Confirmation dialog for destructive actions. With `confirmValue` set, the
 * user must type it (e.g. the resource name) before the action is enabled.
 */
/**
 * Controlled confirmation dialog without a trigger, for actions launched from
 * dropdown menus (the menu closes before the dialog opens).
 */
export function ConfirmDialogControlled({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  pending,
  onConfirm
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  pending?: boolean;
  onConfirm: () => void;
}) {
  const t = useTranslations();
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{t("cancel")}</AlertDialogCancel>
          <Button variant="destructive" disabled={pending} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel,
  confirmValue,
  confirmValueLabel,
  pending = false,
  onConfirm
}: {
  trigger: React.ReactNode;
  title: string;
  description: string;
  confirmLabel: string;
  confirmValue?: string;
  confirmValueLabel?: string;
  pending?: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const blocked = confirmValue !== undefined && typed !== confirmValue;

  async function confirm() {
    await onConfirm();
    setOpen(false);
    setTyped("");
  }

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {confirmValue !== undefined ? (
          <div className="flex flex-col gap-2">
            <Label htmlFor="confirm-value">{confirmValueLabel}</Label>
            <Input
              id="confirm-value"
              value={typed}
              placeholder={confirmValue}
              onChange={(event) => setTyped(event.target.value)}
            />
          </div>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{t("cancel")}</AlertDialogCancel>
          <Button variant="destructive" disabled={blocked || pending} onClick={confirm}>
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
