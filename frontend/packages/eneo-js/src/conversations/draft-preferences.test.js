import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import {
  readConversationDraft,
  rememberConversationDraft,
  resolveConversationDraft
} from "./draft-preferences.js";

const scope = {
  tenantId: "tenant",
  userId: "user",
  partnerType: "default-assistant",
  partnerId: "assistant"
};
const choices = {
  completion_model_id: "model",
  reasoning_effort: "high",
  require_tool_approval: true,
  mcp_server_states: { server: false },
  capability_states: { web_search: false }
};
const originalStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
let values;
beforeEach(() => {
  values = new Map();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      clear: () => values.clear()
    }
  });
});
afterEach(() => {
  if (originalStorage) Object.defineProperty(globalThis, "localStorage", originalStorage);
  else delete globalThis.localStorage;
});

test("remembers the whole setup without a server revision and resets when storage is cleared", () => {
  rememberConversationDraft(scope, choices);
  assert.deepEqual(readConversationDraft(scope), choices);
  const restored = readConversationDraft(scope);
  restored.mcp_server_states.server = true;
  assert.equal(readConversationDraft(scope).mcp_server_states.server, false);
  globalThis.localStorage.clear();
  assert.equal(readConversationDraft(scope), undefined);
});

test("isolates accounts, organizations and conversation partners", () => {
  rememberConversationDraft(scope, choices);
  for (const field of Object.keys(scope)) {
    assert.equal(readConversationDraft({ ...scope, [field]: "other" }), undefined);
  }
});

test("unavailable storage never fails the chat", () => {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    get() {
      throw Error("blocked");
    }
  });
  assert.doesNotThrow(() => rememberConversationDraft(scope, choices));
  assert.equal(readConversationDraft(scope), undefined);
});

test("corrupt, unknown and invalid browser formats fall back to defaults", () => {
  rememberConversationDraft(scope, choices);
  const key = [...values.keys()][0];
  for (const raw of [
    "bad json",
    "null",
    '{"version":2}',
    JSON.stringify({ version: 1, settings: { ...choices, require_tool_approval: "false" } }),
    JSON.stringify({
      version: 1,
      settings: { ...choices, mcp_server_states: { server: "false" } }
    }),
    JSON.stringify({ version: 1, settings: { ...choices, future_safety: true } })
  ]) {
    values.set(key, raw);
    assert.equal(readConversationDraft(scope), undefined);
  }
});

test("a revoked draft model falls back to current defaults while keeping tool and approval choices", async () => {
  const defaults = { ...choices, completion_model_id: "allowed", reasoning_effort: null };
  const resolve = async (settings = defaults) => ({
    revision: 0,
    settings,
    model_unavailable: settings.completion_model_id === "model",
    reasoning_effort_options: []
  });
  const result = await resolveConversationDraft(resolve, choices);
  assert.deepEqual(result.settings, defaults);
  assert.equal(result.model_unavailable, false);
});

test("a retired reasoning choice is cleared on new drafts", async () => {
  const result = await resolveConversationDraft(
    async (settings) => ({ revision: 0, settings, reasoning_effort_options: ["low"] }),
    choices
  );
  assert.equal(result.settings.reasoning_effort, null);
  assert.deepEqual(result.settings.mcp_server_states, choices.mcp_server_states);
});

test("invalid remembered API values use defaults but network failures remain visible", async () => {
  const defaults = { ...choices, reasoning_effort: null };
  const result = await resolveConversationDraft(async (settings) => {
    if (settings) throw Object.assign(new Error("retired option"), { status: 422 });
    return { revision: 0, settings: defaults };
  }, choices);
  assert.deepEqual(result.settings, defaults);
  await assert.rejects(
    resolveConversationDraft(async () => {
      throw Error("offline");
    }, choices),
    /offline/
  );
});
