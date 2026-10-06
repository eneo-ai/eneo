"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { useTranslations } from "next-intl";
import { useId } from "react";

/**
 * Why something cannot be deleted yet: a provider that still has models, or
 * an image model a capability source runs on (the backend refuses both). The
 * menu item says so too; this is what choosing it anyway opens, instead of a
 * confirmation that would fail.
 */
export function DeleteBlockedDialog({
  open,
  onOpenChange,
  title,
  description
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
}) {
  const t = useTranslations();
  const descriptionId = useId();
  // One way out besides Escape and the backdrop: "Stäng" (no header X).
  return (
    <Dialog isOpen={open} onOpenChange={onOpenChange} aria-describedby={descriptionId}>
      <Layout
        height="auto"
        header={<DialogHeader title={title} />}
        content={
          <LayoutContent>
            <p id={descriptionId} className="text-sm">
              {description}
            </p>
          </LayoutContent>
        }
        footer={
          <LayoutFooter>
            <div className="flex justify-end">
              <Button label={t("close")} onClick={() => onOpenChange(false)} />
            </div>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
