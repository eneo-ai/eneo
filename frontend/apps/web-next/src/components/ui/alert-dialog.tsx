"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogSurface,
  DialogTitle,
  DialogTrigger,
  useDialogContext
} from "@/components/ui/dialog";

/*
 * shadcn's AlertDialog API on the same Astryx dialog as dialog.tsx, with the
 * WAI-ARIA alert dialog behaviour of Astryx AlertDialog: role "alertdialog",
 * no close button and no dismissal from the backdrop, Escape cancels, and
 * Cancel (the least destructive choice) has focus when it opens. Astryx
 * AlertDialog itself only takes a title and a description; these dialogs also
 * hold fields and custom actions, so they are composed from the parts.
 */

const AlertDialog = Dialog;
const AlertDialogTrigger = DialogTrigger;
const AlertDialogHeader = DialogHeader;
const AlertDialogFooter = DialogFooter;
const AlertDialogTitle = DialogTitle;
const AlertDialogDescription = DialogDescription;

function AlertDialogContent({
  className,
  children
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  return (
    <DialogSurface role="alertdialog" closeButton={false} className={className}>
      {children}
    </DialogSurface>
  );
}

type AlertDialogButtonProps = React.ComponentProps<typeof Button>;

/**
 * Confirms and closes (unless its click handler calls `preventDefault()`).
 * type="button" like Radix's, so it never submits a surrounding form.
 */
function AlertDialogAction({ onClick, ...props }: AlertDialogButtonProps) {
  const { setOpen } = useDialogContext("AlertDialogAction");
  return (
    <Button
      type="button"
      data-slot="alert-dialog-action"
      {...props}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) setOpen(false);
      }}
    />
  );
}

/** Closes without acting (never submits a form); focused when the dialog opens. */
function AlertDialogCancel({ variant = "outline", onClick, ...props }: AlertDialogButtonProps) {
  const { setOpen } = useDialogContext("AlertDialogCancel");
  return (
    <Button
      type="button"
      data-slot="alert-dialog-cancel"
      data-autofocus=""
      variant={variant}
      {...props}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) setOpen(false);
      }}
    />
  );
}

export {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
};
