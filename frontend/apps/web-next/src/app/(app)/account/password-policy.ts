import type { Schema } from "@/lib/api/models";

/**
 * The local password policy the backend enforces (backend
 * eneo/users/password.py), as `GET /api/v1/users/me/` returns it in
 * `password_change`. The same checks as the SvelteKit account dialog
 * (apps/web passwordChange.ts), for Eneo's own passwords.
 */
export type PasswordPolicy = Readonly<{
  minLength: number;
  maxBytes: number;
  requiresUppercase: boolean;
  requiresLowercase: boolean;
  requiresNumber: boolean;
  requiresSymbol: boolean;
}>;

/** Where the account's password is changed, if here. */
export type PasswordCapability =
  { source: "eneo"; policy: PasswordPolicy } | { source: "external" } | { source: "unavailable" };

/**
 * The capability from the user's `password_change`. A policy with a missing
 * or odd value is never guessed at: the form is then not offered.
 */
export function passwordCapability(
  value: Schema<"UserPublic">["password_change"] | null | undefined
): PasswordCapability {
  if (value?.source === "external") return { source: "external" };
  const policy = value?.source === "eneo" ? value.policy : undefined;
  const positive = (number: unknown): number is number =>
    typeof number === "number" && Number.isSafeInteger(number) && number > 0;
  if (
    !policy ||
    !positive(policy.min_length) ||
    !positive(policy.max_bytes) ||
    typeof policy.requires_uppercase !== "boolean" ||
    typeof policy.requires_lowercase !== "boolean" ||
    typeof policy.requires_number !== "boolean" ||
    typeof policy.requires_symbol !== "boolean"
  ) {
    return { source: "unavailable" };
  }
  return {
    source: "eneo",
    policy: {
      minLength: policy.min_length,
      maxBytes: policy.max_bytes,
      requiresUppercase: policy.requires_uppercase,
      requiresLowercase: policy.requires_lowercase,
      requiresNumber: policy.requires_number,
      requiresSymbol: policy.requires_symbol
    }
  };
}

export type PolicyRule =
  "min_length" | "max_bytes" | "uppercase" | "lowercase" | "number" | "symbol";

/**
 * The policy's rules in the order the backend checks them, each with whether
 * `password` meets it. The minimum counts characters, the maximum UTF-8 bytes
 * (bcrypt's limit), and the classes are ASCII, as in the backend.
 */
export function policyChecks(
  password: string,
  policy: PasswordPolicy
): { rule: PolicyRule; met: boolean }[] {
  const bytes = new TextEncoder().encode(password).byteLength;
  return [
    { rule: "min_length" as const, met: [...password].length >= policy.minLength },
    { rule: "max_bytes" as const, met: bytes <= policy.maxBytes },
    ...(policy.requiresUppercase
      ? [{ rule: "uppercase" as const, met: /[A-Z]/.test(password) }]
      : []),
    ...(policy.requiresLowercase
      ? [{ rule: "lowercase" as const, met: /[a-z]/.test(password) }]
      : []),
    ...(policy.requiresNumber ? [{ rule: "number" as const, met: /[0-9]/.test(password) }] : []),
    ...(policy.requiresSymbol
      ? [{ rule: "symbol" as const, met: /[^A-Za-z0-9]/.test(password) }]
      : [])
  ];
}

/** The first rule `password` breaks, if any. */
export function brokenRule(password: string, policy: PasswordPolicy): PolicyRule | undefined {
  return policyChecks(password, policy).find((check) => !check.met)?.rule;
}
