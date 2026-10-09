import assert from "node:assert/strict";
import test from "node:test";

import { initConversations } from "./conversations.js";

test("turn diagnostics uses the conversation-scoped message endpoint", async () => {
  const diagnostics = {
    session_id: "session-1",
    message_id: "message-1",
    skill_activation: null
  };
  const calls = [];
  const conversations = initConversations({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return diagnostics;
    }
  });

  const result = await conversations.getTurnDiagnostics({
    sessionId: "session-1",
    messageId: "message-1"
  });

  assert.equal(result, diagnostics);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/conversations/{session_id}/messages/{message_id}/diagnostics/",
      request: {
        method: "get",
        params: { path: { session_id: "session-1", message_id: "message-1" } }
      }
    }
  ]);
});

test("ordinary chat requests do not send a debug capture field", async () => {
  const calls = [];
  const conversations = initConversations({
    stream: async (endpoint, request) => calls.push({ endpoint, request })
  });

  await conversations.ask({
    chatPartner: { id: "assistant-1", type: "assistant" },
    question: "Hello",
    files: []
  });

  const body = calls[0].request.requestBody["application/json"];
  assert.equal("debug" in body, false);
});

test("conversation capability opt-outs use purpose fields independently of MCP server IDs", async () => {
  const calls = [];
  const conversations = initConversations({
    stream: async (endpoint, request) => calls.push({ endpoint, request })
  });
  await conversations.ask({
    chatPartner: { id: "assistant-1", type: "assistant" },
    question: "Hello",
    files: [],
    disabledCapabilities: ["image_generation"],
    disabledMcpServerIds: ["ordinary-server"]
  });
  const body = calls[0].request.requestBody["application/json"];
  assert.deepEqual(body.disabled_capabilities, ["image_generation"]);
  assert.deepEqual(body.disabled_mcp_server_ids, ["ordinary-server"]);
});

test("document export availability is a read scoped to the saved document", async () => {
  const calls = [];
  const state = {
    docx: { available: true },
    pdf: { available: false, reason: "format_unsupported" }
  };
  const api = initConversations({
    fetch: async (...args) => {
      calls.push(args);
      return state;
    }
  });
  assert.deepEqual(await api.getDocumentExportAvailability({ sessionId: "s", fileId: "f" }), state);
  assert.deepEqual(calls, [
    [
      "/api/v1/conversations/{session_id}/documents/{file_id}/export/",
      { method: "get", params: { path: { session_id: "s", file_id: "f" } } }
    ]
  ]);
});
