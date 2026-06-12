"use client";

import { useTranslations } from "next-intl";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

/**
 * Publish/unpublish confirmation shared by assistants, group chats and (later)
 * apps. Ported from the Svelte PublishingDialog.
 */
export function PublishDialog({
  open,
  onOpenChange,
  name,
  published,
  pending,
  publishHint,
  onConfirm
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  published: boolean;
  pending: boolean;
  /** Extra hint shown below the description when publishing (not unpublishing). */
  publishHint?: string;
  onConfirm: () => void;
}) {
  const t = useTranslations();
  const action = published ? t("unpublish") : t("publish");
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {action} {name}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {published
              ? t("do_you_really_want_to_unpublish", { name })
              : t("do_you_want_to_publish", { name })}
          </AlertDialogDescription>
        </AlertDialogHeader>
        {!published && publishHint && (
          <p className="text-muted-foreground text-xs">{publishHint}</p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{t("cancel")}</AlertDialogCancel>
          <Button
            variant={published ? "destructive" : "default"}
            disabled={pending}
            onClick={onConfirm}
          >
            {pending ? t("loading") : action}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
