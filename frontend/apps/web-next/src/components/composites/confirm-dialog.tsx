"use client";

import { useId, useState } from "react";
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
 * Controlled confirmation dialog without a trigger, for actions launched from
 * dropdown menus (the menu closes before the dialog opens). While `pending`,
 * neither Cancel nor Escape closes it.
 */
export function ConfirmDialogControlled({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  variant = "destructive",
  pending,
  onConfirm
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  variant?: "default" | "destructive";
  pending?: boolean;
  onConfirm: () => void;
}) {
  const t = useTranslations();
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (next || !pending) onOpenChange(next);
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{t("cancel")}</AlertDialogCancel>
          <Button variant={variant} disabled={pending} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/**
 * Confirmation dialog for destructive actions. With `confirmValue` set, the
 * user must type it (e.g. the resource name) before the action is enabled.
 * While the action runs it cannot be closed; when it fails (the caller reports
 * the error) the dialog stays open with what the user typed.
 */
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
  const inputId = useId();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [running, setRunning] = useState(false);
  const busy = pending || running;
  const blocked = confirmValue !== undefined && typed !== confirmValue;

  function changeOpen(next: boolean) {
    if (!next && busy) return;
    setOpen(next);
    if (!next) setTyped("");
  }

  async function confirm() {
    setRunning(true);
    try {
      await onConfirm();
    } catch {
      // The caller reports the failure (a toast from its mutation); keep the
      // dialog open so the user can retry or cancel.
      return;
    } finally {
      setRunning(false);
    }
    setOpen(false);
    setTyped("");
  }

  return (
    <AlertDialog open={open} onOpenChange={changeOpen}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {confirmValue !== undefined ? (
          <div className="flex flex-col gap-2">
            <Label htmlFor={inputId}>{confirmValueLabel}</Label>
            <Input
              id={inputId}
              value={typed}
              placeholder={confirmValue}
              onChange={(event) => setTyped(event.target.value)}
            />
          </div>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>{t("cancel")}</AlertDialogCancel>
          <Button variant="destructive" disabled={blocked || busy} onClick={() => void confirm()}>
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
