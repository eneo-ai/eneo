"use client";

import { useLocale, useTranslations } from "next-intl";
import type { Schema } from "@/lib/api/models";

/**
 * A property the source system keeps about a document, e.g. a SharePoint
 * library column such as "Dokumenttyp: Rutin", in the source's column order.
 */
export type SourceMetadataEntry = Schema<"SourceMetadataEntry">;

/** Date-only columns arrive as midnight UTC; show the day as written, not shifted to local time. */
const DATE_ONLY = /^(\d{4}-\d{2}-\d{2})T00:00:00(?:\.0+)?(?:Z|\+00:00)$/;

export function formatSourceMetadataValue(
  entry: SourceMetadataEntry,
  options: { locale: string; yes: string; no: string }
): string {
  const values = Array.isArray(entry.value) ? entry.value : [entry.value];
  return values
    .map((value) => {
      switch (entry.kind) {
        case "date": {
          const dateOnly = DATE_ONLY.exec(value);
          if (dateOnly?.[1]) return dateOnly[1];
          const date = new Date(value);
          return Number.isNaN(date.getTime())
            ? value
            : date.toLocaleString(options.locale, { dateStyle: "medium", timeStyle: "short" });
        }
        case "boolean":
          return value.trim().toLowerCase() === "true" ? options.yes : options.no;
        default:
          return value;
      }
    })
    .filter((value) => value.length > 0)
    .join(", ");
}

/** A document's source properties as a description list; nothing when it has none. */
export function SourceMetadataList({ entries }: { entries: readonly SourceMetadataEntry[] }) {
  const t = useTranslations();
  const locale = useLocale();
  if (entries.length === 0) return null;
  const options = { locale, yes: t("yes"), no: t("no") };
  return (
    <dl
      aria-label={t("source_metadata_label")}
      className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm"
    >
      {entries.map((entry) => (
        <div key={entry.name} className="contents">
          <dt className="text-ax-text-secondary">{entry.label}</dt>
          <dd className="break-words">{formatSourceMetadataValue(entry, options)}</dd>
        </div>
      ))}
    </dl>
  );
}
