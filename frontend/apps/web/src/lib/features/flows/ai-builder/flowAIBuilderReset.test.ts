import { describe, expect, it } from "vitest";

import { shouldShowEditStartOver } from "./flowAIBuilderReset";

describe("flowAIBuilderReset", () => {
  it("shows Start over for edit sessions with meaningful state", () => {
    expect(
      shouldShowEditStartOver({
        targetKind: "edit",
        hasSession: true,
        messageCount: 1,
        hasPlan: false,
        isConflict: false,
        statusMessage: null,
        hasApplyError: false,
        hasApplyResult: false,
        isStreaming: false
      })
    ).toBe(true);
  });

  it("hides Start over for empty edit sessions", () => {
    expect(
      shouldShowEditStartOver({
        targetKind: "edit",
        hasSession: true,
        messageCount: 0,
        hasPlan: false,
        isConflict: false,
        statusMessage: null,
        hasApplyError: false,
        hasApplyResult: false,
        isStreaming: false
      })
    ).toBe(false);
  });

  it("hides Start over outside edit mode", () => {
    expect(
      shouldShowEditStartOver({
        targetKind: "create",
        hasSession: true,
        messageCount: 3,
        hasPlan: true,
        isConflict: false,
        statusMessage: null,
        hasApplyError: false,
        hasApplyResult: false,
        isStreaming: false
      })
    ).toBe(false);
  });
});
