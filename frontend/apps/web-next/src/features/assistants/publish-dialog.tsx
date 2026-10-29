"use client";

import { useTranslations } from "use-intl";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";

/**
 * Publish/unpublish confirmation shared by assistants, group chats and apps.
 * Ported from the Svelte PublishingDialog.
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
    <ConfirmDialogControlled
      open={open}
      onOpenChange={onOpenChange}
      title={`${action} ${name}`}
      description={
        published
          ? t("do_you_really_want_to_unpublish", { name })
          : t("do_you_want_to_publish", { name })
      }
      confirmLabel={pending ? t("loading") : action}
      variant={published ? "destructive" : "default"}
      pending={pending}
      onConfirm={onConfirm}
    >
      {!published && publishHint && <p className="text-muted-foreground text-xs">{publishHint}</p>}
    </ConfirmDialogControlled>
  );
}
