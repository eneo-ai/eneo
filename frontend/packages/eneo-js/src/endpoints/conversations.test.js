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

test("consultations update by server ID and preserve separate follow-ups", async () => {
  const consultations = [
    { id: "first", ordinal: 1, status: "running", answer: "" },
    { id: "first", ordinal: 1, status: "complete", answer: "IT answer" },
    { id: "follow-up", ordinal: 2, status: "complete", answer: "IT clarification" }
  ];
  const events = [
    'event: first_chunk\ndata: {"session_id":"s","answer":"","consultations":[]}\n\n',
    ...consultations.map(
      (item) =>
        `event: consultation\ndata: ${JSON.stringify({ session_id: "s", consultations: [item] })}\n\n`
    ),
    'event: text\ndata: {"session_id":"s","answer":"Synthesis","references":[]}\n\n'
  ];
  const api = initConversations(
    createClient({
      baseUrl: "https://eneo.example",
      fetch: async () =>
        new Response(events.join(""), { headers: { "Content-Type": "text/event-stream" } })
    })
  );
  const observed = [];
  const answer = await api.ask({
    chatPartner: { id: "coordinator", type: "assistant" },
    question: "Check",
    files: [],
    callbacks: { onEneoEvent: (event) => observed.push(event) }
  });
  assert.equal(answer.answer, "Synthesis");
  assert.deepEqual(answer.consultations, consultations.slice(1));
  assert.equal(observed.length, 3);
});
