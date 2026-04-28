import { describe, expect, test } from "vitest";

import {
  getDisplayableKnowledgeChunks,
  getKnowledgeReferenceCounts,
  getKnowledgeReferencePreviewReferences,
  normalizeKnowledgeMatchedCount
} from "./flowRunKnowledgeTrace";

describe("flowRunKnowledgeTrace helpers", () => {
  test("uses backend matched count as the matched segment count when available", () => {
    expect(
      getKnowledgeReferenceCounts({
        id: "source-1",
        id_short: "source-1",
        matched_chunk_count: 7,
        chunks: [{ chunk_no: 1, snippet: "Shown preview", score: 0.8 }]
      })
    ).toEqual({ matchedCount: 7, displayedCount: 1, truncated: true });
  });

  test("uses explicit matched count and derives displayed count from snippets", () => {
    expect(
      getKnowledgeReferenceCounts({
        id: "source-1",
        id_short: "source-1",
        matched_chunk_count: 3,
        chunks: [
          { chunk_no: 2, snippet: "Second", score: 0.7 },
          { chunk_no: 1, snippet: "First", score: 0.9 }
        ]
      })
    ).toEqual({ matchedCount: 3, displayedCount: 2, truncated: true });
  });

  test("falls back to returned displayable chunks when counts are unavailable", () => {
    expect(
      getKnowledgeReferenceCounts({
        id: "source-1",
        id_short: "source-1",
        chunks: [
          { chunk_no: 2, snippet: "Second", score: 0.7 },
          { chunk_no: 1, snippet: "", score: 0.9 }
        ]
      })
    ).toEqual({ matchedCount: 1, displayedCount: 1, truncated: false });
  });

  test("filters empty snippets for the displayed chunk list", () => {
    expect(
      getDisplayableKnowledgeChunks([
        { chunk_no: 1, snippet: "Shown", score: 0.9 },
        { chunk_no: 2, snippet: "  ", score: 0.8 }
      ])
    ).toEqual([{ chunk_no: 1, snippet: "Shown", score: 0.9 }]);
  });

  test("normalizes matched counts without allowing them below displayed snippets", () => {
    expect(normalizeKnowledgeMatchedCount(2, 5)).toBe(5);
    expect(normalizeKnowledgeMatchedCount(null, 5)).toBe(5);
    expect(normalizeKnowledgeMatchedCount(9, 5)).toBe(9);
  });

  test("treats nullable backend counts as unknown", () => {
    expect(
      getKnowledgeReferenceCounts({
        id: "source-1",
        id_short: "source-1",
        matched_chunk_count: null,
        chunks: [{ chunk_no: 1, snippet: "Shown", score: 0.9 }]
      })
    ).toEqual({ matchedCount: 1, displayedCount: 1, truncated: false });
  });

  test("limits inline references while preserving the hidden source count", () => {
    const preview = getKnowledgeReferencePreviewReferences(["a", "b", "c", "d", "e"], 4);

    expect(preview.references).toEqual(["a", "b", "c", "d"]);
    expect(preview.hiddenCount).toBe(1);
  });
});
