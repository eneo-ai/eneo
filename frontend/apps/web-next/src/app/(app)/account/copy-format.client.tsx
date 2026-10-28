"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import {
  type AssistantCopyFormat,
  getPreferredAssistantCopyFormat,
  setPreferredAssistantCopyFormat
} from "@/features/chat/copy-assistant-answer";

const COPY_FORMAT_OPTIONS: AssistantCopyFormat[] = ["markdown", "richtext"];

function isAssistantCopyFormat(value: string): value is AssistantCopyFormat {
  return value === "markdown" || value === "richtext";
}

/** The format an answer's copy button puts on the clipboard. */
export function useCopyFormatLabel(): string {
  const t = useTranslations();
  const { settings } = useAppContext();
  return getPreferredAssistantCopyFormat(settings) === "markdown"
    ? t("copy_format_markdown")
    : t("copy_format_richtext");
}

/**
 * The copy format, saved as it is chosen: shown optimistically, put back if
 * saving fails.
 */
export function CopyFormatChoice() {
  const t = useTranslations();
  const { settings } = useAppContext();
  const router = useRouter();
  const serverCopyFormat = getPreferredAssistantCopyFormat(settings);
  const [optimisticCopyFormat, setOptimisticCopyFormat] = useState<AssistantCopyFormat | null>(
    null
  );
  const copyFormat = optimisticCopyFormat ?? serverCopyFormat;
  const [savingCopyFormat, setSavingCopyFormat] = useState(false);

  async function savePreferredCopyFormat(next: string) {
    if (!isAssistantCopyFormat(next) || next === copyFormat || savingCopyFormat) return;

    const previous = optimisticCopyFormat;
    setOptimisticCopyFormat(next);
    setSavingCopyFormat(true);
    try {
      await unwrap(
        browserApi.POST("/api/v1/settings/", {
          body: {
            ...settings,
            chatbot_widget: setPreferredAssistantCopyFormat(settings, next)
          }
        })
      );
      toast.success(t("preferred_copy_format_updated"));
      router.refresh();
    } catch (error) {
      setOptimisticCopyFormat(previous);
      toastApiError(error, t);
    } finally {
      setSavingCopyFormat(false);
    }
  }

  return (
    <RadioGroup
      value={copyFormat}
      disabled={savingCopyFormat}
      className="grid gap-2 sm:grid-cols-2"
      onValueChange={(next) => {
        void savePreferredCopyFormat(next);
      }}
    >
      {COPY_FORMAT_OPTIONS.map((format) => {
        const id = `account-copy-format-${format}`;
        return (
          <Label
            key={format}
            htmlFor={id}
            className="hover:bg-muted/70 flex cursor-pointer items-center gap-3 rounded-md border p-3 text-sm pointer-coarse:min-h-11"
          >
            <RadioGroupItem id={id} value={format} disabled={savingCopyFormat} />
            <span className="font-medium">
              {format === "markdown" ? t("copy_format_markdown") : t("copy_format_richtext")}
            </span>
          </Label>
        );
      })}
    </RadioGroup>
  );
}
