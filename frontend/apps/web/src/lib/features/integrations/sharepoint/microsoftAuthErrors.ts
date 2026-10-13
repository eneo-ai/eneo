export type MicrosoftAuthGuidance = "invalid_client" | "interaction_required" | "invalid_grant";

// AADSTS50076 arrives inside an invalid_grant envelope, so the more specific
// interactive-sign-in case must win over the generic grant failure.
const GUIDANCE_PATTERNS: ReadonlyArray<[MicrosoftAuthGuidance, RegExp]> = [
  ["invalid_client", /AADSTS7000215|invalid_client/i],
  ["interaction_required", /AADSTS50076|interaction_required/i],
  ["invalid_grant", /invalid_grant/i]
];

/** Which short guidance fits a raw Microsoft identity error, if any. */
export function classifyMicrosoftAuthError(
  message: string | null | undefined
): MicrosoftAuthGuidance | null {
  if (!message) return null;
  for (const [guidance, pattern] of GUIDANCE_PATTERNS) {
    if (pattern.test(message)) return guidance;
  }
  return null;
}
