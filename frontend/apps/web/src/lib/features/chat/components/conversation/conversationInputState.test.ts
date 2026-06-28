import { EneoError } from "@eneo/eneo-js";
import { describe, expect, it } from "vitest";
import { getContextErrorInfo, isConversationSubmitDisabled } from "./conversationInputState";

describe("isConversationSubmitDisabled", () => {
  it("does not block sending when only the preflight estimate exceeds context", () => {
    expect(
      isConversationSubmitDisabled({
        isLoading: false,
        isUploading: false,
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
        isUploading: false,
        hasContent: false,
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
