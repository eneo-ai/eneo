import { describe, expect, test } from "vitest";

import {
  flattenKnowledgeTraceSources,
  getKnowledgeTraceSourceTotal,
  isMappedFanOutIncomplete,
  getDisclosedPassages,
  getKnowledgeReferenceCounts,
  getKnowledgeReferencePreviewReferences,
  getWithheldPassages,
  isPassageWithheld,
  normalizeKnowledgeMatchedCount
} from "./flowRunKnowledgeTrace";

const reference = (id: string) => ({
  id,
  id_short: id.slice(0, 8),
  best_score: 0.8,
  matched_chunk_count: 1,
  recorded_passage_count: 0,
  passages: []
});

const passage = (chunkNo: number, text: string | null, extra: Record<string, unknown> = {}) => ({
  chunk_no: chunkNo,
  score: 0.8,
  text,
  recording: "complete" as const,
  passage_bytes: text ? text.length : 12,
  recorded_bytes: text ? text.length : 12,
  ...extra
});

describe("flowRunKnowledgeTrace helpers", () => {
  test("reports matched, recorded and disclosed passage counts separately", () => {
    expect(
      getKnowledgeReferenceCounts({
        id: "source-1",
        id_short: "source-1",
        best_score: 0.8,
        matched_chunk_count: 7,
        recorded_passage_count: 1,
        passages: [passage(1, "Recorded passage")]
      })
    ).toEqual({
      matchedCount: 7,
      recordedCount: 1,
      disclosedCount: 1,
      withheldCount: 0,
      truncated: true
    });
  });

  test("counts a withheld passage as recorded but not disclosed", () => {
    expect(
      getKnowledgeReferenceCounts({
        id: "source-1",
        id_short: "source-1",
        best_score: 0.8,
        matched_chunk_count: 3,
        recorded_passage_count: 2,
        passages: [
          passage(1, "Visible passage"),
          passage(2, null, { disclosure: "text_withheld_sensitive_flow" })
        ]
      })
    ).toEqual({
      matchedCount: 3,
      recordedCount: 2,
      disclosedCount: 1,
      withheldCount: 1,
      truncated: true
    });
  });

  test("falls back to the recorded passages when counts are unavailable", () => {
    expect(
      getKnowledgeReferenceCounts({
        id: "source-1",
        id_short: "source-1",
        best_score: 0.8,
        passages: [passage(2, "Second"), passage(1, "")]
      })
    ).toEqual({
      matchedCount: 2,
      recordedCount: 2,
      disclosedCount: 1,
      withheldCount: 0,
      truncated: false
    });
  });

  test("separates disclosed passages from withheld ones", () => {
    const passages = [
      passage(1, "Shown"),
      passage(2, "  "),
      passage(3, null, { disclosure: "text_withheld_classified_space" })
    ];

    expect(getDisclosedPassages(passages)).toEqual([passages[0]]);
    expect(getWithheldPassages(passages)).toEqual([passages[2]]);
    expect(isPassageWithheld(passages[0])).toBe(false);
    expect(isPassageWithheld(passages[2])).toBe(true);
  });

  test("normalizes matched counts without allowing them below recorded passages", () => {
    expect(normalizeKnowledgeMatchedCount(2, 5)).toBe(5);
    expect(normalizeKnowledgeMatchedCount(null, 5)).toBe(5);
    expect(normalizeKnowledgeMatchedCount(9, 5)).toBe(9);
  });

  test("treats nullable backend counts as unknown", () => {
    expect(
      getKnowledgeReferenceCounts({
        id: "source-1",
        id_short: "source-1",
        best_score: 0.8,
        matched_chunk_count: null,
        recorded_passage_count: null,
        passages: [passage(1, "Shown")]
      })
    ).toEqual({
      matchedCount: 1,
      recordedCount: 1,
      disclosedCount: 1,
      withheldCount: 0,
      truncated: false
    });
  });

  test("limits inline references while preserving the hidden source count", () => {
    const preview = getKnowledgeReferencePreviewReferences(["a", "b", "c", "d", "e"], 4);

    expect(preview.references).toEqual(["a", "b", "c", "d"]);
    expect(preview.hiddenCount).toBe(1);
  });

  test("finds no sources in an empty or absent payload", () => {
    expect(flattenKnowledgeTraceSources(null)).toEqual([]);
    expect(flattenKnowledgeTraceSources({ references: [] })).toEqual([]);
  });

  test("flattens direct references without a call number", () => {
    const sources = flattenKnowledgeTraceSources({
      references: [reference("source-1"), reference("source-2")]
    });

    expect(sources.map((source) => source.reference.id)).toEqual(["source-1", "source-2"]);
    expect(sources.every((source) => source.callNumber === null)).toBe(true);
    expect(sources.map((source) => source.key)).toEqual(["source-1", "source-2"]);
  });

  test("finds sources inside a mapped step's per-call payloads", () => {
    const sources = flattenKnowledgeTraceSources({
      execution_mode: "per_item",
      sources_total: 2,
      items: [{ references: [reference("source-1")] }, { references: [reference("source-2")] }]
    });

    expect(sources.map((source) => source.reference.id)).toEqual(["source-1", "source-2"]);
    expect(sources.map((source) => source.callNumber)).toEqual([1, 2]);
  });

  test("keeps a repeated source id distinct per mapped call", () => {
    const sources = flattenKnowledgeTraceSources({
      execution_mode: "per_source",
      sources: [{ references: [reference("shared")] }, { references: [reference("shared")] }]
    });

    expect(sources).toHaveLength(2);
    expect(sources.map((source) => source.key)).toEqual(["1:shared", "2:shared"]);
    expect(new Set(sources.map((source) => source.key)).size).toBe(2);
  });

  test("reports the mapped total rather than the direct reference count", () => {
    const rag = {
      execution_mode: "per_item",
      sources_total: 2,
      items: [{ references: [reference("source-1")] }, { references: [reference("source-2")] }]
    };
    const sources = flattenKnowledgeTraceSources(rag);

    expect(getKnowledgeTraceSourceTotal(rag, sources.length)).toBe(2);
    expect(getKnowledgeTraceSourceTotal({ references: [] }, 0)).toBe(0);
  });

  test("never reports fewer sources than it actually found", () => {
    expect(getKnowledgeTraceSourceTotal({ unique_sources: 1 }, 3)).toBe(3);
  });

  test("reports a complete fan-out as complete", () => {
    expect(isMappedFanOutIncomplete(null)).toBe(false);
    expect(isMappedFanOutIncomplete({ references: [reference("source-1")] })).toBe(false);
    expect(
      isMappedFanOutIncomplete({
        execution_mode: "per_item",
        mapped_calls_complete: true,
        items: [{ references: [reference("source-1")] }]
      })
    ).toBe(false);
  });

  test("reports a fan-out that stopped partway as incomplete", () => {
    expect(
      isMappedFanOutIncomplete({
        execution_mode: "per_item",
        mapped_calls_complete: false,
        items: [{ references: [reference("source-1")] }]
      })
    ).toBe(true);
  });

  test("finds an incomplete fan-out nested inside a call", () => {
    expect(
      isMappedFanOutIncomplete({
        execution_mode: "per_source",
        mapped_calls_complete: true,
        sources: [{ execution_mode: "per_item", mapped_calls_complete: false, items: [] }]
      })
    ).toBe(true);
  });
});
