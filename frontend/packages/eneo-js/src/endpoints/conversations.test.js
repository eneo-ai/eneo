import assert from "node:assert/strict";
import test from "node:test";

import { createClient, EneoError } from "../client/client.js";
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

test("preflight preserves attachment modes alongside conversation revision", async () => {
  let body;
  const conversations = initConversations({
    fetch: async (_endpoint, request) => {
      body = request.requestBody["application/json"];
      return {};
    }
  });
  await conversations.preflight({
    conversation: { id: "saved" },
    question: "Hello",
    settingsRevision: 3,
    attachments: [{ id: "on-demand", inline_text: false }, { id: "inlined" }]
  });
  assert.equal(body.session_id, "saved");
  assert.equal(body.settings_revision, 3);
  assert.deepEqual(body.attachments, [
    { id: "on-demand", inline_text: false },
    { id: "inlined", inline_text: true }
  ]);
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

test("a failed answer rejects with the reason the stream gave", async () => {
  const events = [
    'event: first_chunk\ndata: {"session_id":"s","answer":""}\n\n',
    'event: text\ndata: {"session_id":"s","answer":"Hej","references":[]}\n\n',
    'event: error\ndata: {"session_id":"s","error":"The AI provider could not be reached.",' +
      '"error_code":503,"code":"provider_unreachable"}\n\n'
  ];
  const conversations = initConversations(
    createClient({
      baseUrl: "https://eneo.example",
      fetch: async () =>
        new Response(events.join(""), { headers: { "Content-Type": "text/event-stream" } })
    })
  );

  await assert.rejects(
    conversations.ask({
      chatPartner: { id: "assistant-1", type: "assistant" },
      question: "Hello",
      files: []
    }),
    (error) => {
      assert.ok(error instanceof EneoError);
      assert.equal(error.response.code, "provider_unreachable");
      assert.equal(error.getReadableMessage(), "The AI provider could not be reached.");
      assert.ok(
        error.request.endpoint.startsWith("STREAM@https://eneo.example/api/v1/conversations/")
      );
      return true;
    }
  );
});

test("a failed answer without a reason is reported as a stream error", async () => {
  const conversations = initConversations(
    createClient({
      baseUrl: "https://eneo.example",
      fetch: async () =>
        new Response('event: error\ndata: {"session_id":"s","error":"Boom","error_code":500}\n\n', {
          headers: { "Content-Type": "text/event-stream" }
        })
    })
  );

  await assert.rejects(
    conversations.ask({
      chatPartner: { id: "assistant-1", type: "assistant" },
      question: "Hello",
      files: []
    }),
    (error) => error instanceof EneoError && error.response.code === "stream_error"
  );
});

test("resolution sends drafts inline but reads saved choices by session identity", async () => {
  const calls = [];
  const conversations = initConversations({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return {};
    }
  });
  const chatPartner = { id: "assistant", type: "default-assistant" };
  const settings = { completion_model_id: "model" };
  await conversations.resolveSettings({ chatPartner, settings });
  await conversations.resolveSettings({ chatPartner, conversation: { id: "saved" }, settings });
  assert.equal(calls[0].endpoint, "/api/v1/conversations/settings/resolve/");
  assert.deepEqual(calls[0].request.requestBody["application/json"], {
    assistant_id: "assistant",
    settings
  });
  assert.deepEqual(calls[1].request.requestBody["application/json"], { session_id: "saved" });
});
