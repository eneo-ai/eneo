"use client";

import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Button } from "@astryxdesign/core/Button";
import { Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useState } from "react";

/**
 * Throws a step's whole recording away with one button, after asking: every
 * part leaves the form, its upload stops or the uploaded file is deleted,
 * and nothing of it stays on the device. While it runs the dialog cannot be
 * closed; the caller moves focus once the button is gone.
 */
export function DiscardRecording({ onDiscard }: { onDiscard: () => Promise<void> }) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  return (
    <>
      <div>
        <Button
          label={t("flow_transcript_discard")}
          icon={<Trash2 aria-hidden="true" />}
          size="sm"
          variant="ghost"
          onClick={() => setOpen(true)}
        />
      </div>
      <AlertDialog
        isOpen={open}
        onOpenChange={(next) => {
          if (!busy) setOpen(next);
        }}
        title={t("flow_transcript_discard_title")}
        description={t("flow_transcript_discard_body")}
        actionLabel={t("flow_transcript_discard")}
        cancelLabel={t("cancel")}
        isActionLoading={busy}
        onAction={async () => {
          if (busy) return;
          setBusy(true);
          try {
            await onDiscard();
          } finally {
            setBusy(false);
            setOpen(false);
          }
        }}
      />
    </>
  );
}
