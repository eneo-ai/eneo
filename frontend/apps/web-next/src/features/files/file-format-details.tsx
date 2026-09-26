"use client";

import { FileCheck2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { formatBytes } from "@/lib/format";
import {
  summarizeFileFormats,
  type AcceptedFormat,
  type FileFormatGroupKind
} from "./file-format-summary";

const GROUP_KEYS: Record<FileFormatGroupKind, string> = {
  documents: "file_format_group_documents",
  images: "file_format_group_images",
  audio: "file_format_group_audio",
  other: "file_format_group_other"
};

/** Shows the server's accepted formats before a user chooses files. */
export function FileFormatDetails({ formats }: { formats: readonly AcceptedFormat[] }) {
  const t = useTranslations();
  const locale = useLocale();
  const groups = summarizeFileFormats(formats);
  if (groups.length === 0) return null;

  const summary = new Intl.ListFormat(locale, { type: "conjunction" }).format(
    groups.map((group) => t(GROUP_KEYS[group.kind]))
  );

  return (
    <details className="border-border group border-t pt-2">
      <summary className="hover:bg-muted focus-visible:outline-ring flex min-h-11 cursor-pointer list-none items-center gap-2 rounded-lg px-2 py-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2 [&::-webkit-details-marker]:hidden">
        <FileCheck2 className="text-muted-foreground size-4 shrink-0" aria-hidden="true" />
        <span className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-sm font-medium">{t("file_types_and_sizes")}</span>
          <span className="text-muted-foreground text-xs">{summary}</span>
        </span>
      </summary>
      <dl className="flex flex-col gap-3 px-2 pt-1 pb-2">
        {groups.map((group) => (
          <div
            key={group.kind}
            className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-3"
          >
            <dt className="shrink-0 text-sm sm:w-40">
              {t(GROUP_KEYS[group.kind])}
              {group.maxSizeBytes !== null && (
                <span className="text-muted-foreground block text-xs">
                  {t("max_size_per_file", { size: formatBytes(group.maxSizeBytes, locale) })}
                </span>
              )}
            </dt>
            <dd className="flex flex-wrap gap-1">
              {group.extensions.map((extension) => (
                <span key={extension} className="rounded-md border px-1.5 py-0.5 font-mono text-xs">
                  {extension}
                </span>
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
