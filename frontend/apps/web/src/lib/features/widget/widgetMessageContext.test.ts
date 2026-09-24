import { describe, expect, it } from "vitest";
import type { ConversationMessage } from "@eneo/eneo-js";
import { messageSources, referenceIndexer } from "./widgetMessageContext";

type Reference = NonNullable<ConversationMessage["references"]>[number];

function reference(id: string, title: string, url: string | null): Reference {
  return {
    id,
    metadata: { title, url, embedding_model_id: "em", size: 10 },
    group_id: null,
    website_id: null
  } as unknown as Reference;
}

const FIRST = "aaaaaaaa-0000-4000-8000-000000000001";
const SECOND = "bbbbbbbb-0000-4000-8000-000000000002";

describe("widget message sources", () => {
  it("keeps two documents apart when only their titles match", () => {
    const message = {
      answer: "",
      mcp_tool_references: [],
      references: [
        reference(FIRST, "Riktlinjer.pdf", null),
        reference(SECOND, "Riktlinjer.pdf", null)
      ]
    };

    expect(messageSources(message).map((source) => source.id)).toEqual([FIRST, SECOND]);
    const index = referenceIndexer(message);
    expect(index(FIRST.slice(0, 8))).toBe(0);
    expect(index(SECOND.slice(0, 8))).toBe(1);
  });

  it("folds passages of one document and pages at one address into one source", () => {
    const message = {
      answer: "",
      mcp_tool_references: [],
      references: [
        reference(FIRST, "Riktlinjer.pdf", null),
        reference(FIRST, "Riktlinjer.pdf", null),
        reference(SECOND, "Avgifter", "https://www.kommun.se/avgifter"),
        reference(
          "cccccccc-0000-4000-8000-000000000003",
          "Avgifter",
          "https://www.kommun.se/avgifter"
        )
      ]
    };

    expect(messageSources(message).map((source) => source.id)).toEqual([FIRST, SECOND]);
    expect(referenceIndexer(message)("cccccccc")).toBe(1);
  });
});
