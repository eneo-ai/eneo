import { describe, expect, it } from "vitest";
import type { ConversationMessage } from "@eneo/eneo-js";
import { listPersistedDebugTurns, projectTurnDebugDetails } from "./turnDebugProjection";

function message(id: string | null, question = "Question"): ConversationMessage {
  return {
    id,
    question,
    answer: "SENSITIVE_ANSWER",
    reasoning: "SENSITIVE_REASONING",
    completion_model: null,
    references: [],
    files: [],
    generated_files: [],
    web_search_references: [],
    mcp_tool_references: [],
    tool_calls: [],
    tools: { assistants: [] }
  };
}

describe("turn debug projection", () => {
  it("keeps persisted turns visible before the live message exists", () => {
    const messages = [message("message-1", "First"), message("message-2", "Second")];

    expect(listPersistedDebugTurns(messages, [])).toEqual([
      { messageId: "message-1", turnNumber: 1, questionExcerpt: "First" },
      { messageId: "message-2", turnNumber: 2, questionExcerpt: "Second" }
    ]);
  });

  it("excludes only messages awaiting canonical persisted metadata", () => {
    const messages = [
      message("message-1", "First"),
      message("message-2", "Second"),
      message("message-3", "Third")
    ];

    expect(listPersistedDebugTurns(messages, ["message-2"])).toEqual([
      { messageId: "message-1", turnNumber: 1, questionExcerpt: "First" },
      { messageId: "message-3", turnNumber: 3, questionExcerpt: "Third" }
    ]);
  });

  it("projects only safe model, tool, reference, and file metadata", () => {
    const source = {
      ...message("message-1"),
      completion_model: {
        id: "model-1",
        name: "Model display",
        litellm_model_name: "provider/model",
        prompt: "SENSITIVE_INSTRUCTIONS"
      },
      tool_calls: [
        {
          server_name: "calendar",
          tool_name: "list_events",
          arguments: { secret: "SENSITIVE_ARGUMENT" },
          result: "SENSITIVE_RESULT",
          result_status: "complete"
        }
      ],
      mcp_tool_references: [
        {
          id: "reference-1",
          uri: "mcp://calendar/events",
          content: "SENSITIVE_CONTENT",
          meta: { title: "Calendar events", incident_reason: "SENSITIVE_INCIDENT" }
        }
      ],
      files: [{ id: "file-1", name: "input.pdf", mimetype: "application/pdf", size: 10 }]
    } as unknown as ConversationMessage;

    const projected = projectTurnDebugDetails(source);
    const serialized = JSON.stringify(projected);

    expect(projected.model).toEqual({
      id: "model-1",
      name: "Model display",
      route: "provider/model"
    });
    expect(projected.tools).toEqual([
      {
        order: 1,
        serverName: "calendar",
        toolName: "list_events",
        status: "complete"
      }
    ]);
    expect(projected.knowledge).toEqual([
      { order: 1, title: "Calendar events", uri: "mcp://calendar/events" }
    ]);
    expect(projected.files[0].name).toBe("input.pdf");
    expect(serialized).not.toMatch(/SENSITIVE_/);
  });
});
