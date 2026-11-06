import { EneoError } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import {
  getContextErrorInfo,
  isConversationSubmitDisabled,
  settingsControlsDisabled,
  toolSelectionUpdate
} from "./conversationInputState";

describe("settingsControlsDisabled", () => {
  const ready = {
    hasSettings: true,
    isLoading: false,
    settingsCompatible: true,
    modelUnavailable: false
  };

  it("keeps every control usable once the choices are loaded", () => {
    expect(settingsControlsDisabled(ready)).toEqual({ model: false, modelDependent: false });
  });

  it("keeps only the model picker usable while the saved model is unavailable", () => {
    expect(settingsControlsDisabled({ ...ready, modelUnavailable: true })).toEqual({
      model: false,
      modelDependent: true
    });
  });

  it("disables everything without loaded choices, during a turn, or for unsupported choices", () => {
    for (const state of [
      { ...ready, hasSettings: false },
      { ...ready, isLoading: true },
      { ...ready, settingsCompatible: false }
    ]) {
      expect(settingsControlsDisabled(state)).toEqual({ model: true, modelDependent: true });
    }
  });
});

describe("toolSelectionUpdate", () => {
  const tools = [
    { id: "server-a", selected: true },
    { id: "server-b", selected: false },
    { id: "capability:web_search", selected: true }
  ];

  it("writes only the tools whose state changed and keeps earlier explicit choices", () => {
    expect(
      toolSelectionUpdate(
        { mcp_server_states: { "server-c": false }, capability_states: { charts: true } },
        tools,
        new Set(["server-a", "server-b", "capability:web_search"])
      )
    ).toEqual({
      mcp_server_states: { "server-c": false, "server-a": false },
      capability_states: { charts: true, web_search: false }
    });
  });

  it("leaves an untouched tool absent so it keeps following the admin default", () => {
    expect(toolSelectionUpdate(undefined, tools, new Set(["server-b"]))).toBeNull();
    expect(toolSelectionUpdate({}, tools, new Set())).toEqual({
      mcp_server_states: { "server-b": true },
      capability_states: {}
    });
  });
});

describe("isConversationSubmitDisabled", () => {
  it("does not block sending when only the preflight estimate exceeds context", () => {
    expect(
      isConversationSubmitDisabled({
        isLoading: false,
        sendPending: false,
        hasContent: true,
        hasCompletionModel: true,
        estimatedExceedsContext: true
      })
    ).toBe(false);
  });

  it("still blocks invalid or busy submissions", () => {
    expect(
      isConversationSubmitDisabled({
        isLoading: false,
        sendPending: false,
        hasContent: false,
        hasCompletionModel: true,
        estimatedExceedsContext: false
      })
    ).toBe(true);
  });
});

describe("isConversationSubmitDisabled", () => {
  it("lets a message with attachments still uploading be sent", () => {
    expect(
      isConversationSubmitDisabled({
        isLoading: false,
        sendPending: false,
        hasContent: true,
        hasCompletionModel: true,
        estimatedExceedsContext: false
      })
    ).toBe(false);
  });

  it("blocks a second submission while the first send is still waiting to be issued", () => {
    expect(
      isConversationSubmitDisabled({
        isLoading: false,
        sendPending: true,
        hasContent: true,
        hasCompletionModel: true,
        estimatedExceedsContext: false
      })
    ).toBe(true);
  });
});

describe("getContextErrorInfo", () => {
  it("reads structured backend token details", () => {
    const error = new EneoError(
      "Input is too long",
      "RESPONSE",
      400,
      9003,
      { details: { tokens_used: 23000, token_limit: 16000 } },
      { endpoint: "/conversations" }
    );

    expect(getContextErrorInfo(error)).toEqual({ used: 23000, limit: 16000 });
  });

  it("recognizes provider context errors without structured details", () => {
    expect(
      getContextErrorInfo(new Error("This model's maximum context length has been exceeded"))
    ).toEqual({});
  });
});
