import type { Schema } from "@/lib/api/models";
import type { StatusTone } from "@/components/composites/status-label";

type Rag = Schema<"FlowRunDebugRag">;
type Reference = Schema<"FlowRunDebugRagReference">;

/** A source a step's search found, with the mapped call it came from. */
export type TraceSource = {
  reference: Reference;
  /** 1-based mapped call the source came from; null for a step that searched once. */
  callNumber: number | null;
  /** Unique even when the same source turns up in several mapped calls. */
  key: string;
};

const MAPPED_CALLS = ["items", "sources"] as const;

/**
 * Every source a step's search found, whether it searched once or once per
 * part (a mapped step records one trace per call). The same source can come
 * up in several calls, so each entry keeps its call number and a key that
 * stays unique across them.
 */
export function traceSources(rag: Rag | null | undefined): TraceSource[] {
  const sources: TraceSource[] = [];
  const visit = (payload: Rag, callNumber: number | null) => {
    for (const reference of payload.references ?? []) {
      if (!reference?.id) continue;
      sources.push({
        reference,
        callNumber,
        key: callNumber === null ? reference.id : `${callNumber}:${reference.id}`
      });
    }
    for (const collection of MAPPED_CALLS) {
      (payload[collection] ?? []).forEach((call, index) => {
        if (call) visit(call, index + 1);
      });
    }
  };
  if (rag) visit(rag, null);
  return sources;
}

/** How many sources the step found: what the core counted, never fewer than are listed. */
export function traceSourceTotal(rag: Rag, listed: number): number {
  const reported = rag.sources_total ?? rag.unique_sources;
  return typeof reported === "number" && reported >= listed ? reported : listed;
}

/**
 * Whether a mapped step stopped before all its calls ran, so the trace
 * covers only the calls that finished.
 */
export function mappedCallsIncomplete(rag: Rag | null | undefined): boolean {
  if (!rag) return false;
  if (rag.mapped_calls_complete === false) return true;
  return MAPPED_CALLS.some((collection) =>
    (rag[collection] ?? []).some((call) => mappedCallsIncomplete(call))
  );
}

/** The calls of a mapped step, one trace each; empty for a step that searched once. */
function mappedCalls(rag: Rag): Rag[] {
  return MAPPED_CALLS.flatMap((collection) => rag[collection] ?? []).filter(Boolean);
}

/** Which call status a mapped step reads as, the first that any call has. */
const MAPPED_STATUS_ORDER = ["error", "timeout", "success", "no_chunks"];

/** How a step's search went, read from its calls when it searched once per part. */
export type TraceSummary = {
  status: string | null;
  /** Passages the search returned. */
  chunks: number;
  /** Time spent searching, all calls together; null when none was recorded. */
  durationMs: number | null;
  errorType: string | null;
};

/**
 * How a step's search went. A mapped step's own trace carries only totals,
 * so its status is the most telling of its calls' (failed, too slow, done,
 * nothing found, else the first call's), and its passages and search time
 * are those of all its calls together.
 */
export function traceSummary(rag: Rag): TraceSummary {
  const calls = mappedCalls(rag);
  if (calls.length === 0) {
    return {
      status: rag.status ?? null,
      chunks: rag.chunks_retrieved ?? 0,
      durationMs: typeof rag.retrieval_duration_ms === "number" ? rag.retrieval_duration_ms : null,
      errorType: rag.retrieval_error_type ?? null
    };
  }
  const summaries = calls.map(traceSummary);
  const statuses = summaries.map((summary) => summary.status);
  const durations = summaries
    .map((summary) => summary.durationMs)
    .filter((value): value is number => value !== null);
  return {
    status:
      rag.status ??
      MAPPED_STATUS_ORDER.find((status) => statuses.includes(status)) ??
      statuses.find((status) => status !== null) ??
      null,
    chunks: rag.chunks_retrieved ?? summaries.reduce((sum, summary) => sum + summary.chunks, 0),
    durationMs:
      typeof rag.retrieval_duration_ms === "number"
        ? rag.retrieval_duration_ms
        : durations.length > 0
          ? durations.reduce((sum, value) => sum + value, 0)
          : null,
    errorType:
      rag.retrieval_error_type ?? summaries.find((summary) => summary.errorType)?.errorType ?? null
  };
}

/** Statuses of steps that never search knowledge: a row of zeros would only puzzle. */
const NO_KNOWLEDGE_SEARCH = new Set([
  "",
  "skipped",
  "skipped_no_knowledge",
  "skipped_transcribe_only",
  "skipped_speaker_mapping"
]);

/**
 * Whether the step's trace belongs in the knowledge section: it searched,
 * or was set up to search and was skipped (no input, no service), or found
 * sources.
 */
export function showsKnowledgeTrace(summary: TraceSummary, sourceCount: number): boolean {
  return sourceCount > 0 || !NO_KNOWLEDGE_SEARCH.has(summary.status ?? "");
}

const STATUS_VIEWS: Record<string, { key: string; tone: StatusTone }> = {
  success: { key: "flow_run_knowledge_status_success", tone: "success" },
  no_chunks: { key: "flow_run_knowledge_status_no_chunks", tone: "neutral" },
  timeout: { key: "flow_run_knowledge_status_timeout", tone: "error" },
  error: { key: "flow_run_knowledge_status_error", tone: "error" },
  skipped_no_input: { key: "flow_run_knowledge_status_skipped_no_input", tone: "warning" },
  skipped_no_service: { key: "flow_run_knowledge_status_skipped_no_service", tone: "warning" },
  skipped_no_knowledge: { key: "flow_run_knowledge_status_skipped_no_knowledge", tone: "neutral" },
  skipped_transcribe_only: {
    key: "flow_run_knowledge_status_skipped_transcribe_only",
    tone: "neutral"
  },
  skipped_speaker_mapping: { key: "flow_run_knowledge_status_skipped", tone: "neutral" },
  // Rows stored before speaker mapping declared its own status.
  skipped: { key: "flow_run_knowledge_status_skipped", tone: "neutral" }
};

/**
 * The search's outcome as a sentence and a tone: done, nothing found, too
 * slow, failed, or skipped and why. A status the runtime recorded that has
 * no sentence reads "unknown", never the identifier.
 */
export function knowledgeStatusView(status: string | null | undefined): {
  key: string;
  tone: StatusTone;
} {
  return STATUS_VIEWS[status ?? ""] ?? { key: "unknown", tone: "neutral" };
}

/** What a source can be found by in the all-sources search: its names, container, address and id. */
function searchText(reference: Reference): string {
  return [
    reference.display_title,
    reference.source_display_name,
    reference.source_title,
    reference.title,
    reference.source_url,
    reference.source_container_name,
    reference.source_container_display_name,
    reference.source_container_label,
    reference.id_short,
    reference.id
  ]
    .filter((value): value is string => typeof value === "string")
    .join(" ")
    .toLowerCase();
}

/** The sources whose names, container, address or id contain the query (any case). */
export function filterTraceSources(sources: readonly TraceSource[], query: string): TraceSource[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...sources];
  return sources.filter((source) => searchText(source.reference).includes(needle));
}

/** A source's best match as a whole percent, 0 to 100. */
export function relevancePercent(score: number | null | undefined): number {
  const value = Number(score ?? 0);
  if (!Number.isFinite(value)) return 0;
  return Math.round(Math.min(1, Math.max(0, value)) * 100);
}

/**
 * What the trace says about passage detail: how many passages this reader
 * may not see, else for how many of the listed sources passages were kept.
 */
export function passageDetailNote(
  rag: Rag,
  listed: number
):
  | { kind: "withheld"; count: number }
  | { kind: "partial"; detailed: number; total: number }
  | null {
  const withheld = rag.passages_withheld ?? 0;
  if (withheld > 0) return { kind: "withheld", count: withheld };
  const detailed = rag.sources_with_recorded_passages;
  if (typeof detailed === "number" && listed > 0 && detailed < listed) {
    return { kind: "partial", detailed, total: listed };
  }
  return null;
}
