"use client";

import { useAnnounce, useClipboard } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";

/**
 * One-time secret display: shown exactly once after creation/rotation, with
 * a copy button and a "this won't be shown again" warning. The key wraps
 * instead of scrolling and selects as a whole, for copying by hand; the copy
 * is announced (Astryx useClipboard), and a refused clipboard says so.
 */
export function SecretRevealDialog({
  title,
  secret,
  onClose
}: {
  title: string;
  secret: string | null;
  onClose: () => void;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const { copy, isCopied } = useClipboard({ announce: t("copied_to_clipboard") });
  const [copyFailed, setCopyFailed] = useState(false);
  const failureId = useId();

  async function copySecret() {
    if (!secret) return;
    const copied = await copy(secret);
    setCopyFailed(!copied);
    if (!copied) announce(t("ui_copy_failed_copy_by_hand"));
  }

  function close() {
    setCopyFailed(false);
    onClose();
  }

  return (
    <Dialog open={secret !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <Alert>
          <AlertTitle>{t("api_keys_important")}</AlertTitle>
          <AlertDescription>{t("api_keys_copy_warning")}</AlertDescription>
        </Alert>
        <div className="flex items-start gap-2">
          <code className="bg-muted min-w-0 flex-1 rounded-md px-3 py-2 font-mono text-sm break-all select-all">
            {secret}
          </code>
          <IconButton
            label={t("api_keys_copy_to_clipboard")}
            tooltip={t("api_keys_copy_to_clipboard")}
            icon={isCopied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
            aria-describedby={copyFailed ? failureId : undefined}
            onClick={() => void copySecret()}
          />
        </div>
        {copyFailed ? (
          <p id={failureId} className="text-destructive text-sm">
            {t("ui_copy_failed_copy_by_hand")}
          </p>
        ) : null}
        <DialogFooter>
          <Button onClick={close}>{t("done")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
