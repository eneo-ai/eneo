import { m } from "$lib/paraglide/messages";

export type MicrosoftAuthGuidance = "invalid_client" | "interaction_required" | "invalid_grant";

// AADSTS50076 arrives inside an invalid_grant envelope, so the more specific
// interactive-sign-in case must win over the generic grant failure.
const GUIDANCE_PATTERNS: ReadonlyArray<[MicrosoftAuthGuidance, RegExp]> = [
  ["invalid_client", /AADSTS7000215|invalid_client/i],
  ["interaction_required", /AADSTS50076|interaction_required/i],
  // AADSTS9002313 ("Invalid request") is what a refresh with a stale or
  // garbled refresh token returns; signing in again is the remedy.
  ["invalid_grant", /invalid_grant|AADSTS9002313/i]
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

export function getMicrosoftAuthGuidanceText(kind: MicrosoftAuthGuidance): string {
  switch (kind) {
    case "invalid_client":
      return m.sharepoint_auth_guidance_invalid_client();
    case "interaction_required":
      return m.sharepoint_auth_guidance_interaction_required();
    case "invalid_grant":
      return m.sharepoint_auth_guidance_invalid_grant();
  }
}
