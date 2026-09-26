import { queryOptions } from "@tanstack/react-query";
import type { useTranslations } from "next-intl";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

/**
 * The local password policy the backend enforces for passwords stored in Eneo
 * (backend eneo/users/password.py): a user's own change and the passwords
 * admins set. The same checks as the SvelteKit app (apps/web
 * passwordChange.ts), used by the account page and the admin user editor.
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
 * A policy as the backend sent it, or null when a value is missing or odd:
 * a policy is never guessed at.
 */
export function readPasswordPolicy(
  value: Schema<"LocalPasswordPolicy"> | null | undefined
): PasswordPolicy | null {
  const positive = (number: unknown): number is number =>
    typeof number === "number" && Number.isSafeInteger(number) && number > 0;
  if (
    !value ||
    !positive(value.min_length) ||
    !positive(value.max_bytes) ||
    typeof value.requires_uppercase !== "boolean" ||
    typeof value.requires_lowercase !== "boolean" ||
    typeof value.requires_number !== "boolean" ||
    typeof value.requires_symbol !== "boolean"
  ) {
    return null;
  }
  return {
    minLength: value.min_length,
    maxBytes: value.max_bytes,
    requiresUppercase: value.requires_uppercase,
    requiresLowercase: value.requires_lowercase,
    requiresNumber: value.requires_number,
    requiresSymbol: value.requires_symbol
  };
}

/** The signed-in user's capability, from `password_change` on `/users/me/`. */
export function passwordCapability(
  value: Schema<"UserPublic">["password_change"] | null | undefined
): PasswordCapability {
  if (value?.source === "external") return { source: "external" };
  const policy = readPasswordPolicy(value?.source === "eneo" ? value.policy : undefined);
  return policy ? { source: "eneo", policy } : { source: "unavailable" };
}

export const PASSWORD_POLICY_KEY = ["password-policy"] as const;

/**
 * The policy for passwords an admin sets for others, whatever the admin's
 * own login (GET /api/v1/users/password-policy/). Null when it cannot be read.
 */
export function passwordPolicyQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: PASSWORD_POLICY_KEY,
    queryFn: async (): Promise<PasswordPolicy | null> =>
      readPasswordPolicy(await unwrap(api.GET("/api/v1/users/password-policy/"))),
    // Set by the deployment, not by anyone using the app.
    staleTime: Infinity
  });
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

type Translate = ReturnType<typeof useTranslations>;

/** A rule in the words of the SvelteKit password checklist. */
export function policyRuleText(t: Translate, rule: PolicyRule, policy: PasswordPolicy): string {
  switch (rule) {
    case "min_length":
      return t("password_policy_min_length", { min: policy.minLength });
    case "max_bytes":
      return t("password_policy_max_bytes", { max: policy.maxBytes });
    case "uppercase":
      return t("password_policy_uppercase");
    case "lowercase":
      return t("password_policy_lowercase");
    case "number":
      return t("password_policy_number");
    case "symbol":
      return t("password_policy_symbol");
  }
}

/** The rules a new password must meet, as sentences for a field's description. */
export function policyRequirements(t: Translate, policy: PasswordPolicy): string {
  // bcrypt's byte limit is left out, as in SvelteKit: it is checked on save.
  return policyChecks("", policy)
    .filter(({ rule }) => rule !== "max_bytes")
    .map(({ rule }) => `${policyRuleText(t, rule, policy)}.`)
    .join(" ");
}

/**
 * What is wrong with a new password and its confirmation, in words for each
 * field. `required`: a password must be set (a new account, one's own change);
 * otherwise both may stay empty (an admin keeping a user's password).
 */
export function newPasswordErrors(
  t: Translate,
  {
    password,
    confirmation,
    policy,
    required
  }: { password: string; confirmation: string; policy: PasswordPolicy; required: boolean }
): { password?: string; confirmation?: string } {
  if (!required && !password && !confirmation) return {};
  const rule = password ? brokenRule(password, policy) : undefined;
  return {
    password: !password
      ? t("change_password_new_required")
      : rule
        ? policyRuleText(t, rule, policy)
        : undefined,
    confirmation:
      password === confirmation
        ? undefined
        : confirmation
          ? t("change_password_mismatch")
          : t("change_password_confirm_required")
  };
}
