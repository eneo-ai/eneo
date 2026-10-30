"use client";

import { useClipboard } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Check, Copy } from "lucide-react";
import { useTranslations } from "use-intl";
import { toast } from "@/lib/toast";

/** A value as the text a copy puts on the clipboard: text as it is, anything else as JSON. */
export function copyText(value: unknown): string {
  return typeof value === "string" ? value : (JSON.stringify(value, null, 2) ?? "");
}

/**
 * Copies what a step produced, was sent or was asked, as plain text: the
 * icon turns into a check and the copy is announced; a copy the browser
 * refuses says so.
 */
export function CopyButton({ label, value }: { label: string; value: unknown }) {
  const t = useTranslations();
  const { copy, isCopied } = useClipboard({ announce: t("copied_to_clipboard") });
  return (
    <IconButton
      label={label}
      tooltip={label}
      icon={isCopied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      variant="ghost"
      size="sm"
      onClick={async () => {
        if (!(await copy(copyText(value)))) toast.error(t("copy_failed"));
      }}
    />
  );
}
