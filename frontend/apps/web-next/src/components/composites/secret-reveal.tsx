"use client";

import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
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
 * a copy button and a "this won't be shown again" warning.
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
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!secret) return;
    await navigator.clipboard.writeText(secret);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Dialog open={secret !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <Alert>
          <AlertTitle>{t("api_keys_important")}</AlertTitle>
          <AlertDescription>{t("api_keys_copy_warning")}</AlertDescription>
        </Alert>
        <div className="flex items-center gap-2">
          <code className="bg-muted min-w-0 flex-1 overflow-x-auto rounded-md px-3 py-2 font-mono text-sm whitespace-nowrap">
            {secret}
          </code>
          <Button
            variant="outline"
            size="icon"
            onClick={copy}
            aria-label={t("api_keys_copy_to_clipboard")}
          >
            {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
          </Button>
        </div>
        <DialogFooter>
          <Button onClick={onClose}>{t("done")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
