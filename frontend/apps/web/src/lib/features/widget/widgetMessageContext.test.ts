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

  describe("knowledge the assistant searched with the knowledge tool", () => {
    type ToolReference = NonNullable<ConversationMessage["mcp_tool_references"]>[number];

    function passage(id: string, document: string, meta: Record<string, unknown>): ToolReference {
      return {
        id,
        uri: `eneo://info-blob/${document}#chunk-${id.slice(-1)}`,
        mime_type: "text/plain",
        content: null,
        meta: { info_blob_id: document, ...meta },
        tool_call_id: null,
        mcp_tool_name: null
      } as unknown as ToolReference;
    }

    const cite = (id: string) => `<inref id="${id.slice(0, 8)}"/>`;
    const UPLOAD = "dddddddd-0000-4000-8000-000000000004";
    const PAGE = "eeeeeeee-0000-4000-8000-000000000005";

    it("lists a cited passage as its document: a page by its address, an upload by its id", () => {
      const upload = passage("c0ffee01-0000-4000-8000-000000000001", UPLOAD, {
        title: "Taxa.pdf"
      });
      const page = passage("c0ffee02-0000-4000-8000-000000000002", PAGE, {
        title: "Avgifter",
        url: "https://www.kommun.se/avgifter"
      });
      const uncited = passage("c0ffee03-0000-4000-8000-000000000003", FIRST, {
        title: "Ociterad"
      });
      const message = {
        answer: `Taxan ${cite(upload.id)}, avgiften ${cite(page.id)}.`,
        references: [],
        mcp_tool_references: [upload, page, uncited]
      };

      expect(messageSources(message)).toEqual([
        { id: UPLOAD, title: "Taxa.pdf", url: null, document: true },
        {
          id: PAGE,
          title: "Avgifter",
          url: "https://www.kommun.se/avgifter",
          document: true
        }
      ]);
      const index = referenceIndexer(message);
      expect(index("c0ffee01")).toBe(0);
      expect(index("c0ffee02")).toBe(1);
    });

    it("folds passages of one document, and one the question also carried, into one source", () => {
      const first = passage("c0ffee01-0000-4000-8000-000000000001", FIRST, {
        title: "Riktlinjer.pdf"
      });
      const later = passage("c0ffee02-0000-4000-8000-000000000002", FIRST, {
        title: "Riktlinjer.pdf"
      });
      const message = {
        answer: `Så ${cite(first.id)}. Och så ${cite(later.id)}.`,
        references: [reference(FIRST, "Riktlinjer.pdf", null)],
        mcp_tool_references: [first, later]
      };

      expect(messageSources(message).map((source) => source.id)).toEqual([FIRST]);
      const index = referenceIndexer(message);
      expect([index("c0ffee01"), index("c0ffee02"), index(FIRST.slice(0, 8))]).toEqual([0, 0, 0]);
    });

    it("never links an address that is not http(s)", () => {
      const sneaky = passage("c0ffee01-0000-4000-8000-000000000001", UPLOAD, {
        title: "Taxa.pdf",
        url: "javascript:alert(1)"
      });
      const message = {
        answer: cite(sneaky.id),
        references: [],
        mcp_tool_references: [sneaky]
      };

      expect(messageSources(message)[0]).toMatchObject({ url: null, document: true });
    });
  });
});
