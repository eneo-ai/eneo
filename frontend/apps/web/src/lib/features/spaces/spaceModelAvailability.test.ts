import { describe, expect, it } from "vitest";

import {
  hasAccessibleCompletionModel,
  hasAccessibleTranscriptionModel,
  spaceCanCreateApps
} from "./spaceModelAvailability";

describe("spaceModelAvailability", () => {
  it("uses model accessibility instead of model list presence", () => {
    expect(hasAccessibleCompletionModel([{ can_access: false }])).toBe(false);
    expect(hasAccessibleTranscriptionModel([{ can_access: false }])).toBe(false);
  });

  it("allows app creation only when completion and transcription models are accessible", () => {
    expect(
      spaceCanCreateApps({
        completion_models: [{ can_access: true }],
        transcription_models: [{ can_access: true }]
      })
    ).toBe(true);

    expect(
      spaceCanCreateApps({
        completion_models: [{ can_access: true }],
        transcription_models: [{ can_access: false }]
      })
    ).toBe(false);
  });
});
