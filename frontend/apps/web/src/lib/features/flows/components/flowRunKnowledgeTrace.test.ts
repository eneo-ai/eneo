import { describe, expect, test } from "vitest";

import {
  getKnowledgeReferenceMatchCount,
  getKnowledgeReferencePreviewReferences
} from "./flowRunKnowledgeTrace";

describe("flowRunKnowledgeTrace helpers", () => {
  test("uses backend hit count as the matched segment count when available", () => {
    expect(
      getKnowledgeReferenceMatchCount({
        id: "source-1",
        id_short: "source-1",
        hit_count: 7,
        chunks: [{ chunk_no: 1, snippet: "Shown preview", score: 0.8 }]
      })
    ).toBe(7);
  });

  test("falls back to returned chunks when hit count is unavailable", () => {
    expect(
      getKnowledgeReferenceMatchCount({
        id: "source-1",
        id_short: "source-1",
        chunks: [
          { chunk_no: 2, snippet: "Second", score: 0.7 },
          { chunk_no: 1, snippet: "First", score: 0.9 }
        ]
      })
    ).toBe(2);
  });

  test("limits inline references while preserving the hidden source count", () => {
    const preview = getKnowledgeReferencePreviewReferences(["a", "b", "c", "d", "e"], 4);

    expect(preview.references).toEqual(["a", "b", "c", "d"]);
    expect(preview.hiddenCount).toBe(1);
  });
});
