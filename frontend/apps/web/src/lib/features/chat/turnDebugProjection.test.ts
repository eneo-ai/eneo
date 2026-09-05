import { describe, expect, it } from "vitest";
import type { ConversationMessage } from "@eneo/eneo-js";
import {
  listPersistedDebugTurns,
  projectTurnDebugDetails,
  readToolUsage
} from "./turnDebugProjection";

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
    mcp_tool_references: [],
    tool_calls: [],
    tools: { assistants: [] }
  };
}

describe("turn debug projection", () => {
  it("keeps persisted turns visible before the live message exists", () => {
    const messages = [message("message-1", "First"), message("message-2", "Second")];

    expect(listPersistedDebugTurns(messages, [])).toEqual([
      { messageId: "message-1", turnNumber: 1, createdAt: null },
      { messageId: "message-2", turnNumber: 2, createdAt: null }
    ]);
  });

  it("excludes only messages whose diagnostics are not persisted yet", () => {
    const messages = [
      message("message-1", "First"),
      message("message-2", "Second"),
      message("message-3", "Third")
    ];

    expect(listPersistedDebugTurns(messages, ["message-2"])).toEqual([
      { messageId: "message-1", turnNumber: 1, createdAt: null },
      { messageId: "message-3", turnNumber: 3, createdAt: null }
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
          uri: "SENSITIVE_URI",
          content: "SENSITIVE_CONTENT",
          meta: { title: "SENSITIVE_TITLE", incident_reason: "SENSITIVE_INCIDENT" }
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
        status: "complete",
        usage: null
      }
    ]);
    expect(projected.knowledge).toEqual([{ order: 1, title: "MCP", uri: null }]);
    expect(projected.files).toEqual([
      {
        order: 1,
        id: "file-1",
        name: "input.pdf",
        mimetype: "application/pdf",
        size: 10,
        kind: "input"
      }
    ]);
    expect(serialized).not.toMatch(/SENSITIVE_/);
  });

  it("reads provider usage from the tool result's gen_ai meta and nothing else", () => {
    const source = {
      ...message("message-1"),
      tool_calls: [
        {
          server_name: "image_generation",
          tool_name: "generate_image",
          result_status: "succeeded",
          meta: {
            "gen_ai.provider.name": "openai",
            "gen_ai.request.model": "gpt-image-1",
            "gen_ai.usage.input_tokens": 38,
            "gen_ai.usage.output_tokens": 1056,
            "com.example/trace": "SENSITIVE_META"
          }
        }
      ]
    } as unknown as ConversationMessage;

    const projected = projectTurnDebugDetails(source);

    expect(projected.tools[0].usage).toEqual({
      provider: "openai",
      model: "gpt-image-1",
      inputTokens: 38,
      outputTokens: 1056
    });
    expect(JSON.stringify(projected)).not.toMatch(/SENSITIVE_/);
  });

  it("treats meta without gen_ai attributes as no usage", () => {
    expect(readToolUsage({ "com.example/trace": "abc" })).toBeNull();
    expect(readToolUsage(null)).toBeNull();
    expect(readToolUsage({ "gen_ai.usage.input_tokens": "38" })).toBeNull();
    expect(readToolUsage({ "gen_ai.response.model": "gpt-image-1-2025" })).toEqual({
      provider: null,
      model: "gpt-image-1-2025",
      inputTokens: null,
      outputTokens: null
    });
  });

  it("prefers the activation evidence for model id and route, keeping the display name", () => {
    const source = {
      ...message("message-1"),
      completion_model: {
        id: "model-1",
        name: "Model display",
        litellm_model_name: "gpt-x"
      }
    } as unknown as ConversationMessage;

    const projected = projectTurnDebugDetails(source, {
      id: "deployment-1",
      route: "provider/gpt-x"
    });

    expect(projected.model).toEqual({
      id: "deployment-1",
      name: "Model display",
      route: "provider/gpt-x"
    });
  });

  it("projects tool metadata from the live streaming field", () => {
    const source = {
      ...message("message-1"),
      mcp_tool_calls: [
        {
          server_name: "warehouse",
          tool_name: "query",
          arguments: { secret: "SENSITIVE_ARGUMENT" },
          result: "SENSITIVE_RESULT",
          result_status: "complete"
        }
      ]
    } as unknown as ConversationMessage;

    const projected = projectTurnDebugDetails(source);

    expect(projected.tools).toEqual([
      {
        order: 1,
        serverName: "warehouse",
        toolName: "query",
        status: "complete",
        usage: null
      }
    ]);
    expect(JSON.stringify(projected)).not.toMatch(/SENSITIVE_/);
  });

  it("uses body-free activation evidence when the stream has no model object", () => {
    const projected = projectTurnDebugDetails(message("message-1"), {
      id: "model-1",
      route: "provider/model"
    });

    expect(projected.model).toEqual({
      id: "model-1",
      name: "provider/model",
      route: "provider/model"
    });
  });
});
