import { describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import {
  filterTraceSources,
  knowledgeStatusView,
  mappedCallsIncomplete,
  passageDetailNote,
  relevancePercent,
  showsKnowledgeTrace,
  traceSourceTotal,
  traceSources,
  traceSummary
} from "./run-knowledge-trace";

type Rag = Schema<"FlowRunDebugRag">;

function reference(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    id_short: id.slice(0, 8),
    best_score: 0.5,
    matched_chunk_count: 1,
    recorded_passage_count: 1,
    ...overrides
  } as Schema<"FlowRunDebugRagReference">;
}

describe("traceSources", () => {
  it("lists a single search's sources without a call number", () => {
    const sources = traceSources({ references: [reference("a"), reference("b")] });
    expect(sources.map((source) => [source.key, source.callNumber])).toEqual([
      ["a", null],
      ["b", null]
    ]);
  });

  it("numbers a mapped step's sources by their call and keeps repeated sources apart", () => {
    const rag: Rag = {
      execution_mode: "per_item",
      items: [{ references: [reference("a")] }, { references: [reference("a"), reference("b")] }]
    };
    expect(traceSources(rag).map((source) => [source.key, source.callNumber])).toEqual([
      ["1:a", 1],
      ["2:a", 2],
      ["2:b", 2]
    ]);
  });

  it("skips a reference without an id", () => {
    expect(traceSources({ references: [reference("")] })).toEqual([]);
  });
});

describe("traceSourceTotal", () => {
  it("takes the core's count, never fewer than are listed", () => {
    expect(traceSourceTotal({ sources_total: 9 }, 3)).toBe(9);
    expect(traceSourceTotal({ unique_sources: 2 }, 3)).toBe(3);
    expect(traceSourceTotal({}, 4)).toBe(4);
  });
});

describe("traceSummary", () => {
  it("reads a single search as recorded", () => {
    expect(
      traceSummary({
        status: "timeout",
        chunks_retrieved: 0,
        retrieval_duration_ms: 30000,
        retrieval_error_type: "TimeoutError"
      })
    ).toEqual({ status: "timeout", chunks: 0, durationMs: 30000, errorType: "TimeoutError" });
  });

  it("reads a mapped step from its calls: the most telling status, passages and time summed", () => {
    const rag: Rag = {
      execution_mode: "per_source",
      mapped_calls_complete: true,
      sources: [
        { status: "success", chunks_retrieved: 3, retrieval_duration_ms: 100 },
        {
          status: "error",
          chunks_retrieved: 0,
          retrieval_duration_ms: 50,
          retrieval_error_type: "ConnectionError"
        },
        { status: "no_chunks", chunks_retrieved: 0 }
      ]
    };
    expect(traceSummary(rag)).toEqual({
      status: "error",
      chunks: 3,
      durationMs: 150,
      errorType: "ConnectionError"
    });
  });

  it("has no search time when no call recorded one", () => {
    expect(traceSummary({ items: [{ status: "success" }] }).durationMs).toBeNull();
  });
});

describe("showsKnowledgeTrace", () => {
  it("shows a search that ran or was skipped for want of input or service", () => {
    for (const status of ["success", "no_chunks", "timeout", "error", "skipped_no_input"]) {
      expect(showsKnowledgeTrace(traceSummary({ status }), 0)).toBe(true);
    }
  });

  it("leaves out a step that never searches knowledge, unless it found sources", () => {
    for (const status of [
      "skipped",
      "skipped_no_knowledge",
      "skipped_transcribe_only",
      "skipped_speaker_mapping"
    ]) {
      expect(showsKnowledgeTrace(traceSummary({ status }), 0)).toBe(false);
    }
    expect(showsKnowledgeTrace(traceSummary({}), 0)).toBe(false);
    expect(showsKnowledgeTrace(traceSummary({}), 2)).toBe(true);
  });
});

describe("knowledgeStatusView", () => {
  it("gives every status the runtime writes a sentence and a tone", () => {
    expect(knowledgeStatusView("success")).toEqual({
      key: "flow_run_knowledge_status_success",
      tone: "success"
    });
    expect(knowledgeStatusView("timeout").tone).toBe("error");
    expect(knowledgeStatusView("skipped_no_service").key).toBe(
      "flow_run_knowledge_status_skipped_no_service"
    );
  });

  it("reads a status it does not know as unknown, never the identifier", () => {
    expect(knowledgeStatusView("some_future_status")).toEqual({ key: "unknown", tone: "neutral" });
  });
});

describe("mappedCallsIncomplete", () => {
  it("is true when the step, or a nested call, stopped before all its calls ran", () => {
    expect(mappedCallsIncomplete({ mapped_calls_complete: false })).toBe(true);
    expect(mappedCallsIncomplete({ items: [{ mapped_calls_complete: false }] })).toBe(true);
    expect(mappedCallsIncomplete({ mapped_calls_complete: true, items: [{}] })).toBe(false);
    expect(mappedCallsIncomplete(null)).toBe(false);
  });
});

describe("filterTraceSources", () => {
  const sources = traceSources({
    references: [
      reference("blob-1", { source_display_name: "Plan- och bygglagen" }),
      reference("blob-2", { source_container_display_name: "Socialtjänst", title: "Riktlinjer" }),
      reference("blob-3", { source_url: "https://example.org/taxa" })
    ]
  });

  it("matches names, container, address and id, in any case", () => {
    expect(filterTraceSources(sources, "BYGG").map((source) => source.key)).toEqual(["blob-1"]);
    expect(filterTraceSources(sources, "socialtj").map((source) => source.key)).toEqual(["blob-2"]);
    expect(filterTraceSources(sources, "taxa").map((source) => source.key)).toEqual(["blob-3"]);
    expect(filterTraceSources(sources, "blob-2").map((source) => source.key)).toEqual(["blob-2"]);
  });

  it("keeps every source for an empty query", () => {
    expect(filterTraceSources(sources, "  ")).toHaveLength(3);
  });
});

describe("relevancePercent", () => {
  it("is the score as a whole percent within 0 and 100", () => {
    expect(relevancePercent(0.823)).toBe(82);
    expect(relevancePercent(1.4)).toBe(100);
    expect(relevancePercent(-0.2)).toBe(0);
    expect(relevancePercent(null)).toBe(0);
  });
});

describe("passageDetailNote", () => {
  it("counts withheld passages before saying for how many sources passages were kept", () => {
    expect(
      passageDetailNote({ passages_withheld: 2, sources_with_recorded_passages: 1 }, 3)
    ).toEqual({ kind: "withheld", count: 2 });
    expect(passageDetailNote({ sources_with_recorded_passages: 1 }, 3)).toEqual({
      kind: "partial",
      detailed: 1,
      total: 3
    });
    expect(passageDetailNote({ sources_with_recorded_passages: 3 }, 3)).toBeNull();
  });
});
