"use client";

import { useTranslations } from "use-intl";

/** A plain-text file, with a notice when only its beginning was read. */
export function TextPreview({ text, truncated }: { text: string; truncated: boolean }) {
  return (
    <>
      <div className="min-h-0 flex-1 overflow-auto">
        <pre className="text-ax-text p-6 font-mono text-sm break-words whitespace-pre-wrap">
          {text}
        </pre>
      </div>
      {truncated && <TruncatedNotice />}
    </>
  );
}

/** Only the beginning of the file was read. */
export function TruncatedNotice() {
  const t = useTranslations();
  return (
    <p className="text-ax-text-secondary border-ax-border shrink-0 border-t px-4 py-2 text-xs">
      {t("file_preview_text_truncated")}
    </p>
  );
}
