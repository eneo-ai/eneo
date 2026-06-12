import { describe, expect, it } from "vitest";
import { mapSessionMessages } from "./map-session";
import type { Schema } from "@/lib/api/models";

type PersistedMessage = Schema<"Message">;

const baseMessage: PersistedMessage = {
  id: "m1",
  question: "What is Eneo?",
  answer: "An AI platform.",
  references: [],
  files: [],
  generated_files: [],
  web_search_references: [],
  tools: { assistants: [] }
};

describe("mapSessionMessages", () => {
  it("maps a question/answer pair to user + assistant messages", () => {
    const messages = mapSessionMessages([baseMessage]);

    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({
      id: "m1-q",
      role: "user",
      parts: [{ type: "text", text: "What is Eneo?" }]
    });
    expect(messages[1]).toMatchObject({ id: "m1", role: "assistant" });
    expect(messages[1]!.parts.at(-1)).toEqual({ type: "text", text: "An AI platform." });
  });

  it("maps references to source-document parts before the answer text", () => {
    const messages = mapSessionMessages([
      {
        ...baseMessage,
        references: [
          {
            id: "blob-1",
            metadata: { title: "Doc title", embedding_model_id: "e", size: 1 }
          } as PersistedMessage["references"][number]
        ]
      }
    ]);

    const parts = messages[1]!.parts;
    expect(parts[0]).toMatchObject({
      type: "source-document",
      sourceId: "blob-1",
      title: "Doc title"
    });
  });

  it("maps persisted tool calls to dynamic-tool parts with error states", () => {
    const messages = mapSessionMessages([
      {
        ...baseMessage,
        tool_calls: [
          {
            server_name: "files",
            tool_name: "read_file",
            tool_call_id: "call-1",
            arguments: { path: "a.txt" },
            result_status: "succeeded"
          },
          {
            server_name: "files",
            tool_name: "write_file",
            tool_call_id: "call-2",
            result_status: "failed"
          }
        ]
      }
    ]);

    const parts = messages[1]!.parts;
    expect(parts[0]).toMatchObject({
      type: "dynamic-tool",
      toolName: "read_file",
      toolCallId: "call-1",
      state: "output-available"
    });
    expect(parts[1]).toMatchObject({
      type: "dynamic-tool",
      toolCallId: "call-2",
      state: "output-error",
      errorText: "failed"
    });
  });

  it("carries attachments, generated files and tokens in metadata", () => {
    const file = { id: "f1", name: "a.pdf", mimetype: "application/pdf", size: 5 };
    const messages = mapSessionMessages([
      {
        ...baseMessage,
        files: [file as PersistedMessage["files"][number]],
        generated_files: [file as PersistedMessage["files"][number]],
        num_tokens_question: 12,
        num_tokens_answer: 34
      }
    ]);

    expect(messages[0]!.metadata?.files?.[0]?.name).toBe("a.pdf");
    expect(messages[1]!.metadata?.generatedFiles?.[0]?.name).toBe("a.pdf");
    expect(messages[1]!.metadata?.tokens).toEqual({ prompt: 12, completion: 34 });
  });

  it("is lenient about missing ids and unknown data", () => {
    const messages = mapSessionMessages([
      { ...baseMessage, id: null, references: [{} as never] },
      { ...baseMessage, id: undefined as never }
    ]);

    expect(messages).toHaveLength(4);
    expect(messages[0]!.id).toBe("history-0-q");
    // The empty reference is skipped, not thrown on.
    expect(messages[1]!.parts).toHaveLength(1);
  });
});
