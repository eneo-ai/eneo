import type { components } from "@eneo/eneo-js";
import { formatDateTime } from "$lib/core/formatting/dateTime";

/**
 * A property the source system keeps about a document, e.g. a SharePoint
 * library column such as "Dokumenttyp: Rutin". Ordered as the source orders
 * its columns; `kind` says how to present the stored text value.
 */
export type SourceMetadataEntry = components["schemas"]["SourceMetadataEntry"];

export type SourceMetadataLabels = { yes: string; no: string };

/** Date-only columns arrive as midnight UTC; show the day as written, not shifted to local time. */
const DATE_ONLY = /^(\d{4}-\d{2}-\d{2})T00:00:00(?:\.0+)?(?:Z|\+00:00)$/;

function formatScalar(
  value: string,
  kind: SourceMetadataEntry["kind"],
  labels: SourceMetadataLabels
): string {
  switch (kind) {
    case "date": {
      const dateOnly = DATE_ONLY.exec(value);
      if (dateOnly) return dateOnly[1];
      return formatDateTime(value) || value;
    }
    case "boolean":
      return value.trim().toLowerCase() === "true" ? labels.yes : labels.no;
    default:
      return value;
  }
}

/** The entry's value as people should read it; multi-value entries are comma separated. */
export function formatSourceMetadataValue(
  entry: SourceMetadataEntry,
  labels: SourceMetadataLabels
): string {
  const values = Array.isArray(entry.value) ? entry.value : [entry.value];
  return values
    .map((value) => formatScalar(value, entry.kind ?? "text", labels))
    .filter((value) => value.length > 0)
    .join(", ");
}

/** True when a document carries at least one source property. */
export function hasSourceMetadata(
  blob: { source_metadata?: SourceMetadataEntry[] | null } | null | undefined
): blob is { source_metadata: SourceMetadataEntry[] } {
  return Array.isArray(blob?.source_metadata) && blob.source_metadata.length > 0;
}
