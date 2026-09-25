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

test("personal model selection is sent for both token preflight and the answer", async () => {
  const requests = [];
  const conversations = initConversations({
    fetch: async (_endpoint, request) => {
      requests.push(request);
      return { input_tokens: 0, file_tokens: 0, model_name: "model-b", context_window: 64000 };
    },
    stream: async (_endpoint, request) => requests.push(request)
  });
  const params = {
    chatPartner: { id: "assistant-1", type: "default-assistant" },
    question: "Hello",
    files: [],
    settings: { completion_model_id: "model-b" }
  };

  await conversations.preflight(params);
  await conversations.ask(params);

  assert.equal(requests[0].requestBody["application/json"].settings.completion_model_id, "model-b");
  assert.equal(requests[1].requestBody["application/json"].settings.completion_model_id, "model-b");
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

test("saving conversation choices uses the expected revision", async () => {
  const calls = [];
  const conversations = initConversations({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { revision: 4, settings: { require_tool_approval: true } };
    }
  });
  const result = await conversations.updateSettings(
    { id: "saved" },
    { require_tool_approval: true },
    3
  );
  assert.equal(result.revision, 4);
  assert.equal(calls[0].endpoint, "/api/v1/conversations/{session_id}/settings/");
  assert.deepEqual(calls[0].request.requestBody["application/json"], {
    expected_revision: 3,
    settings: { require_tool_approval: true }
  });
});
