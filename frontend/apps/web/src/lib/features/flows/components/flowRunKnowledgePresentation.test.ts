import { describe, expect, test } from "vitest";

import {
  formatKnowledgeSourceLabel,
  getKnowledgeSourceSearchText,
  getKnowledgeRelevanceBadgeClass,
  getKnowledgeRelevanceLevel
} from "./flowRunKnowledgePresentation";

describe("flowRunKnowledgePresentation helpers", () => {
  test("classifies relevance from numeric scores", () => {
    expect(getKnowledgeRelevanceLevel(0.7)).toBe("high");
    expect(getKnowledgeRelevanceLevel(0.4)).toBe("moderate");
    expect(getKnowledgeRelevanceLevel(0.1)).toBe("low");
  });

  test("returns semantic badge classes for relevance", () => {
    expect(getKnowledgeRelevanceBadgeClass(0.7)).toBe("bg-positive-dimmer text-positive-stronger");
    expect(getKnowledgeRelevanceBadgeClass(0.4)).toBe("bg-warning-dimmer text-warning-stronger");
    expect(getKnowledgeRelevanceBadgeClass(0.1)).toBe("bg-negative-dimmer text-negative-stronger");
  });

  test("formats URL-like source titles into readable labels", () => {
    expect(
      formatKnowledgeSourceLabel(
        "https://kunskap.example.se/dokument/mycket-lang-sokvag-for-underlag",
        null,
        { maxPathLength: 24 }
      )
    ).toBe("kunskap.example.se/dokument/mycket-lang...");
  });

  test("prefers human source titles over source URLs", () => {
    expect(
      formatKnowledgeSourceLabel(
        "Beslut till underlag",
        "https://kunskap.example.se/beslut/underlag"
      )
    ).toBe("Beslut till underlag");
  });

  test("builds searchable source text from display metadata", () => {
    expect(
      getKnowledgeSourceSearchText({
        id: "source-1",
        id_short: "source",
        title: "https://kunskap.example.se/beslut/underlag",
        source_display_name: "Beslut till underlag",
        source_container_label: "Kunskapsbanken",
        matched_chunk_count: 1,
        recorded_passage_count: 0,
        best_score: 0.8
      })
    ).toContain("kunskapsbanken");
  });
});
