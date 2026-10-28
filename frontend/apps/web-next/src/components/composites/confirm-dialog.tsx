"use client";

import { useId, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
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
 * dropdown menus (the menu closes before the dialog opens) and every other
 * confirmation a caller opens itself. While `pending`, neither Cancel, Escape
 * nor an outside click closes it, and the confirm button stays enabled (so it
 * keeps focus) but ignores a press. `children` renders under the description
 * (an impact or risk list, a hint).
 */
export function ConfirmDialogControlled({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  variant = "destructive",
  pending,
  onConfirm,
  children
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  variant?: "default" | "destructive";
  pending?: boolean;
  onConfirm: () => void;
  children?: ReactNode;
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
        {children}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{t("cancel")}</AlertDialogCancel>
          <Button variant={variant} aria-busy={pending || undefined} onClick={() => onConfirm()}>
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/**
 * Confirmation dialog for destructive actions. With `confirmValue` set, the
 * user must type it (e.g. the resource name): confirming without it says so at
 * the field, which takes focus. While the action runs it cannot be closed and
 * the confirm button keeps focus; when it fails (the caller reports the error)
 * the dialog stays open with what the user typed. `children` renders under the
 * description (what will be lost).
 */
export function ConfirmDialog({
  trigger,
  title,
  description,
  confirmLabel,
  confirmValue,
  confirmValueLabel,
  pending = false,
  onConfirm,
  children
}: {
  trigger: React.ReactNode;
  title: string;
  description: string;
  confirmLabel: string;
  confirmValue?: string;
  confirmValueLabel?: string;
  pending?: boolean;
  onConfirm: () => void | Promise<unknown>;
  children?: ReactNode;
}) {
  const t = useTranslations();
  const inputId = useId();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [running, setRunning] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = pending || running;
  const blocked = confirmValue !== undefined && typed !== confirmValue;
  const problem =
    submitted && blocked ? t("form_problem_confirm_mismatch", { value: confirmValue }) : null;

  function changeOpen(next: boolean) {
    if (!next && busy) return;
    setOpen(next);
    if (!next) {
      setTyped("");
      setSubmitted(false);
    }
  }

  async function confirm() {
    if (busy) return;
    if (blocked) {
      revealProblems(() => setSubmitted(true), inputRef.current);
      return;
    }
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
    setSubmitted(false);
  }

  return (
    <AlertDialog open={open} onOpenChange={changeOpen}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {children}
        {confirmValue !== undefined ? (
          <div className="flex flex-col gap-2">
            <Label htmlFor={inputId}>{confirmValueLabel}</Label>
            <Input
              ref={inputRef}
              id={inputId}
              value={typed}
              placeholder={confirmValue}
              onChange={(event) => setTyped(event.target.value)}
              {...fieldProblemProps(inputId, problem)}
            />
            <FieldProblem id={inputId} problem={problem} />
          </div>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>{t("cancel")}</AlertDialogCancel>
          <Button
            variant="destructive"
            aria-busy={busy || undefined}
            onClick={() => void confirm()}
          >
            {confirmLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
