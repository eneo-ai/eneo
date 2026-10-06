import { describe, expect, it } from "vitest";
import type { Schema } from "@/lib/api/models";
import type { EneoUIMessage } from "@/lib/chat/types";
import { answeringAssistantFromParts, mcpReferencesFromParts, mergeSources } from "./message-parts";

type Part = EneoUIMessage["parts"][number];

const sessionPart: Part = {
  type: "data-session",
  data: {
    session_id: "s1",
    completion_model: null,
    files: [],
    web_search_references: [{ id: "web-1", title: "Web result", url: "https://example.com" }],
    answering_assistant: { id: "assistant-1", handle: "ops" }
  }
};

describe("message parts", () => {
  it("merges live web-search references from data-session parts", () => {
    expect(mergeSources([sessionPart])).toEqual([
      {
        key: "web-web-1",
        sourceId: "web-1",
        title: "Web result",
        url: "https://example.com"
      }
    ]);
  });

  it("reads the live answering assistant from data-session parts", () => {
    expect(answeringAssistantFromParts([sessionPart])).toEqual({
      id: "assistant-1",
      handle: "ops"
    });
  });

  it("merges live MCP resource references into sources and excludes image references", () => {
    const textReference = {
      id: "abcd1234-0000-0000-0000-000000000000",
      uri: "mcp://files/a.md",
      mime_type: "text/markdown",
      content: "snippet",
      meta: { title: "A file", section: "Intro" },
      tool_call_id: "call-1",
      mcp_tool_name: "files__read_file"
    } satisfies Schema<"McpToolReferencePublic">;
    const imageReference = {
      id: "ffff1234-0000-0000-0000-000000000000",
      uri: "https://example.com/image.png",
      mime_type: "image/png",
      content: null,
      meta: { title: "Image" },
      tool_call_id: "call-1",
      mcp_tool_name: "files__read_file"
    } satisfies Schema<"McpToolReferencePublic">;
    const mcpPart: Part = {
      type: "data-mcp-tool-references",
      data: { mcp_tool_references: [textReference, imageReference] }
    };

    const references = mcpReferencesFromParts([mcpPart], [textReference]);
    expect(references).toEqual([textReference, imageReference]);
    expect(mergeSources([mcpPart], [], references)).toEqual([
      {
        key: "mcp-abcd1234-0000-0000-0000-000000000000",
        sourceId: "abcd1234-0000-0000-0000-000000000000",
        title: "A file -> Intro",
        mcpSnippet: {
          uri: "mcp://files/a.md",
          content: "snippet",
          pageRange: null,
          section: "Intro"
        }
      }
    ]);
  });

  it("keeps separate knowledge excerpts and removes the MCP document header from their text", () => {
    const references: Schema<"McpToolReferencePublic">[] = [0, 1, 2].map((chunk) => ({
      id: `reference-${chunk}`,
      uri: `eneo://info-blob/document-1#chunk-${chunk}`,
      content: `Title: kaffe_tips\ndocument_id: document-1\n\nPassage ${chunk + 1}`,
      meta: { title: "kaffe_tips", info_blob_id: "document-1" }
    }));

    const sources = mergeSources([], [], references);

    expect(sources.map((source) => source.sourceId)).toEqual([
      "reference-0",
      "reference-1",
      "reference-2"
    ]);
    expect(sources.map((source) => source.mcpSnippet?.excerptNumber)).toEqual([1, 2, 3]);
    expect(sources.map((source) => source.mcpSnippet?.content)).toEqual([
      "Passage 1",
      "Passage 2",
      "Passage 3"
    ]);
  });
});
