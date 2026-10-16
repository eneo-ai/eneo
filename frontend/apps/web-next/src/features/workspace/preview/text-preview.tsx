"use client";

import { useTranslations } from "next-intl";
import { ANSWER_TEXT_CLASS, MessageResponse } from "@/components/ai-elements/message";
import { cn } from "@/lib/utils";

/** A Markdown or plain-text file, with a notice when only its beginning was read. */
export function TextPreview({
  kind,
  text,
  truncated
}: {
  kind: "markdown" | "text";
  text: string;
  truncated: boolean;
}) {
  const t = useTranslations();
  return (
    <>
      <div className="min-h-0 flex-1 overflow-auto">
        {kind === "markdown" ? (
          <MessageResponse className={cn(ANSWER_TEXT_CLASS, "mx-auto max-w-[72ch] p-6")}>
            {text}
          </MessageResponse>
        ) : (
          <pre className="text-ax-text p-6 font-mono text-sm break-words whitespace-pre-wrap">
            {text}
          </pre>
        )}
      </div>
      {truncated && (
        <p className="text-ax-text-secondary border-ax-border shrink-0 border-t px-4 py-2 text-xs">
          {t("file_preview_text_truncated")}
        </p>
      )}
    </>
  );
}
