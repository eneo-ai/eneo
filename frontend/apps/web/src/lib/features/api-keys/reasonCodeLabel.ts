import { m } from "$lib/paraglide/messages";

const reasonCodeMap: Record<string, () => string> = {
  security_concern: () => m.api_keys_reason_security_concern(),
  abuse_detected: () => m.api_keys_reason_abuse_detected(),
  user_request: () => m.api_keys_reason_user_request(),
  admin_action: () => m.api_keys_reason_admin_action(),
  policy_violation: () => m.api_keys_reason_policy_violation(),
  key_compromised: () => m.api_keys_reason_key_compromised(),
  user_offboarding: () => m.api_keys_reason_user_offboarding(),
  rotation_completed: () => m.api_keys_reason_rotation_completed(),
  scope_removed: () => m.api_keys_reason_scope_removed(),
  other: () => m.api_keys_reason_other()
};

export function getReasonCodeLabel(code: string | null | undefined): string | null {
  if (!code) return null;
  return reasonCodeMap[code]?.() ?? code;
}
