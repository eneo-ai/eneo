import { describe, expect, it } from "vitest";
import { classifyMicrosoftAuthError } from "./microsoftAuthErrors";

describe("classifyMicrosoftAuthError", () => {
  it.each([
    ["AADSTS7000215: Invalid client secret provided.", "invalid_client"],
    ["invalid_client: The request body must contain client_secret", "invalid_client"],
    [
      "invalid_grant: AADSTS50076: Due to a configuration change made by your administrator, you must use multi-factor authentication",
      "interaction_required"
    ],
    ["interaction_required: user must sign in", "interaction_required"],
    ["invalid_grant: AADSTS700082: The refresh token has expired", "invalid_grant"],
    ["AADSTS9002313: Invalid request. Request is malformed or invalid.", "invalid_grant"],
    ["Connection reset by peer", null],
    ["", null],
    [null, null]
  ])("maps %j to %j", (message, guidance) => {
    expect(classifyMicrosoftAuthError(message)).toBe(guidance);
  });
});
