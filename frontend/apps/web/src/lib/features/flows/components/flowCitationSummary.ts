/**
 * Strict boundary adapter for the citation summary the backend attaches to
 * step results and review-checkpoint responses. The generated
 * `FlowCitationSummary` contract is canonical; this adapter only decides how
 * an untyped payload maps onto it:
 *
 * - `null`/`undefined` payload → `null` (no summary to show: citations off,
 *   or the backend could support no claim either way)
 * - well-formed payload → the typed summary
 * - present but malformed payload → an explicit `unavailable` summary, so a
 *   contract breach is visible instead of masquerading as citations-off
 */

import type { FlowCitationSource, FlowCitationSummary } from "@eneo/eneo-js";

export type { FlowCitationSource, FlowCitationSummary };

const STATUSES: ReadonlySet<FlowCitationSummary["status"]> = new Set([
  "observed",
  "missing_required_citations",
  "unknown_citation_ids_present",
  "citations_on_without_sources",
  "unavailable"
]);

const UNAVAILABLE: FlowCitationSummary = {
  status: "unavailable",
  sources: [],
  matched_cited_source_count: 0,
  sources_truncated: false,
  stale_after_edit: false
};

function parseSource(raw: unknown): FlowCitationSource | null {
  if (typeof raw !== "object" || raw === null) return null;
  const item = raw as Record<string, unknown>;
  if (typeof item.identity_resolved !== "boolean") return null;
  if (item.display_name !== null && typeof item.display_name !== "string") return null;
  if (item.container_label !== null && typeof item.container_label !== "string") return null;
  return {
    identity_resolved: item.identity_resolved,
    display_name: item.display_name,
    container_label: item.container_label
  };
}

export function readFlowCitationSummary(value: unknown): FlowCitationSummary | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "object") return UNAVAILABLE;
  const record = value as Record<string, unknown>;
  if (
    typeof record.status !== "string" ||
    !STATUSES.has(record.status as FlowCitationSummary["status"]) ||
    !Array.isArray(record.sources) ||
    !Number.isSafeInteger(record.matched_cited_source_count) ||
    (record.matched_cited_source_count as number) < 0 ||
    typeof record.sources_truncated !== "boolean" ||
    typeof record.stale_after_edit !== "boolean"
  ) {
    return UNAVAILABLE;
  }
  const matchedCount = record.matched_cited_source_count as number;
  // The projection's fixed invariants: the list caps at 20 entries, the
  // matched count equals the list length unless the list was truncated at
  // exactly the cap. Anything else is a contract breach, not data to render —
  // and the cap is enforced before iterating so a corrupt oversized array is
  // rejected without walking it.
  if (record.sources.length > 20) return UNAVAILABLE;
  if (record.sources_truncated) {
    if (record.sources.length !== 20 || matchedCount <= 20) return UNAVAILABLE;
  } else if (matchedCount !== record.sources.length) {
    return UNAVAILABLE;
  }
  const sources: FlowCitationSource[] = [];
  for (const raw of record.sources) {
    const source = parseSource(raw);
    if (source === null) return UNAVAILABLE;
    sources.push(source);
  }
  return {
    status: record.status as FlowCitationSummary["status"],
    sources,
    matched_cited_source_count: matchedCount,
    sources_truncated: record.sources_truncated,
    stale_after_edit: record.stale_after_edit
  };
}

/** The summary field as attached by the backend on public payloads. */
export function readAttachedCitationSummary(container: unknown): FlowCitationSummary | null {
  if (typeof container !== "object" || container === null) return null;
  return readFlowCitationSummary((container as Record<string, unknown>).citation_summary);
}
