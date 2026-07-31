import { EneoError } from "@eneo/eneo-js";
import { describe, expect, it, vi } from "vitest";
import en from "../../../../messages/en.json";
import sv from "../../../../messages/sv.json";

vi.mock("$lib/paraglide/messages", () => ({
  m: {
    eneo_error_9042: () => "Credential encryption must be configured before saving secrets.",
    eneo_error_9048: () => "Slug taken.",
    eneo_error_9049: () => "Published Skills are kept.",
    eneo_error_9050: () => "An App run needs it.",
    eneo_error_9051: () => "Still attached.",
    eneo_error_9052: () => "The execution block changed.",
    request_failed: () => "Request failed."
  }
}));

import { getErrorMessage } from "./getErrorMessage";

/** Reason codes for the Skill lifecycle conflicts, and the code that used to
    answer for all of them: the AI model display-name collision. */
const SKILL_CONFLICT_CODES = [9048, 9049, 9050, 9051, 9052] as const;
const MODEL_NAME_COLLISION = 9017;

describe("getErrorMessage", () => {
  it("localizes missing credential encryption configuration", () => {
    const error = new EneoError(
      "Backend fallback",
      "RESPONSE",
      503,
      9042,
      {},
      { endpoint: "POST@/api/v1/admin/model-providers/" }
    );

    expect(getErrorMessage(error)).toBe(
      "Credential encryption must be configured before saving secrets."
    );
  });

  it("gives every Skill lifecycle conflict its own localized recovery instruction", () => {
    const localized = Object.fromEntries(
      SKILL_CONFLICT_CODES.map((code) => [
        code,
        getErrorMessage(
          // An unmapped code falls back to this backend text, so seeing it
          // here means the conflict never reached the localization table.
          new EneoError("Backend fallback", "RESPONSE", 409, code, {}, { endpoint: "" })
        )
      ])
    );

    expect(localized).toEqual({
      9048: "Slug taken.",
      9049: "Published Skills are kept.",
      9050: "An App run needs it.",
      9051: "Still attached.",
      9052: "The execution block changed."
    });
  });

  it("never answers a Skill conflict with the model display-name copy", () => {
    for (const catalogue of [en, sv] as Record<string, string>[]) {
      const modelCopy = catalogue[`eneo_error_${MODEL_NAME_COLLISION}`];
      expect(modelCopy).toBeTruthy();

      for (const code of SKILL_CONFLICT_CODES) {
        const skillCopy = catalogue[`eneo_error_${code}`];
        expect(skillCopy, `eneo_error_${code}`).toBeTruthy();
        expect(skillCopy).not.toBe(modelCopy);
      }
    }
  });
});
