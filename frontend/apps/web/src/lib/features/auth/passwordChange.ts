export type PasswordPolicy = Readonly<{
  minLength: number;
  maxBytes: number | null;
  requiresUppercase: boolean;
  requiresLowercase: boolean;
  requiresNumber: boolean;
  requiresSymbol: boolean;
}>;

export type PasswordChangeCapability =
  | Readonly<{
      source: "eneo" | "zitadel";
      policy: PasswordPolicy;
    }>
  | Readonly<{
      source: "external" | "unavailable";
      policy: null;
    }>;

export type AvailablePasswordChangeCapability = Extract<
  PasswordChangeCapability,
  { source: "eneo" | "zitadel" }
>;

export type PasswordField = "currentPassword" | "newPassword" | "confirmPassword";

export type PasswordValidationError =
  | "required"
  | "current_password_incorrect"
  | "confirmation_mismatch"
  | "password_unchanged"
  | "policy_rejected"
  | "too_short"
  | "too_short_bytes"
  | "too_long_bytes"
  | "uppercase_required"
  | "lowercase_required"
  | "number_required"
  | "symbol_required";

export type PasswordFieldErrors = Partial<Record<PasswordField, PasswordValidationError>>;

export type PasswordChangeFormError =
  "not_available" | "provider_rejected" | "rate_limited" | "request_failed";

export type PasswordChangeActionFailure = Readonly<{
  fieldErrors?: PasswordFieldErrors;
  formError?: PasswordChangeFormError;
}>;

export type PasswordChangeValues = Readonly<{
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
}>;

export const UNAVAILABLE_PASSWORD_CHANGE: PasswordChangeCapability = Object.freeze({
  source: "unavailable",
  policy: null
});

/** Normalize the backend-owned local policy; never guess missing policy values. */
export function normalizeLocalPasswordCapability(value: unknown): PasswordChangeCapability {
  if (typeof value !== "object" || value === null) return UNAVAILABLE_PASSWORD_CHANGE;
  const policy = value as Record<string, unknown>;
  const minLength = policy.min_length;
  const maxBytes = policy.max_bytes;
  if (
    typeof minLength !== "number" ||
    !Number.isSafeInteger(minLength) ||
    minLength < 1 ||
    typeof maxBytes !== "number" ||
    !Number.isSafeInteger(maxBytes) ||
    maxBytes < 1 ||
    typeof policy.requires_uppercase !== "boolean" ||
    typeof policy.requires_lowercase !== "boolean" ||
    typeof policy.requires_number !== "boolean" ||
    typeof policy.requires_symbol !== "boolean"
  ) {
    return UNAVAILABLE_PASSWORD_CHANGE;
  }
  return {
    source: "eneo",
    policy: {
      minLength,
      maxBytes,
      requiresUppercase: policy.requires_uppercase,
      requiresLowercase: policy.requires_lowercase,
      requiresNumber: policy.requires_number,
      requiresSymbol: policy.requires_symbol
    }
  };
}

export type PasswordPolicyError = Extract<
  PasswordValidationError,
  | "too_short"
  | "too_short_bytes"
  | "too_long_bytes"
  | "uppercase_required"
  | "lowercase_required"
  | "number_required"
  | "symbol_required"
>;

export type PasswordPolicyCheck = Readonly<{
  error: PasswordPolicyError;
  satisfied: boolean;
}>;

/** The same checks drive validation and live policy feedback. */
export function getPasswordPolicyChecks(
  password: string,
  capability: AvailablePasswordChangeCapability
): PasswordPolicyCheck[] {
  const { policy, source } = capability;
  const byteLength = new TextEncoder().encode(password).byteLength;
  // Zitadel's Auth API counts UTF-8 bytes and uses ASCII character classes.
  // Eneo's local policy counts Unicode characters for its minimum instead.
  // See zitadel/internal/domain/policy_password_complexity.go.
  const length = source === "zitadel" ? byteLength : [...password].length;

  const checks: PasswordPolicyCheck[] = [];
  if (policy.minLength > 0) {
    checks.push({
      error: source === "zitadel" ? "too_short_bytes" : "too_short",
      satisfied: length >= policy.minLength
    });
  }
  if (policy.maxBytes !== null) {
    checks.push({ error: "too_long_bytes", satisfied: byteLength <= policy.maxBytes });
  }
  if (policy.requiresUppercase) {
    checks.push({ error: "uppercase_required", satisfied: /[A-Z]/.test(password) });
  }
  if (policy.requiresLowercase) {
    checks.push({ error: "lowercase_required", satisfied: /[a-z]/.test(password) });
  }
  if (policy.requiresNumber) {
    checks.push({ error: "number_required", satisfied: /[0-9]/.test(password) });
  }
  if (policy.requiresSymbol) {
    checks.push({ error: "symbol_required", satisfied: /[^A-Za-z0-9]/.test(password) });
  }
  return checks;
}

export function validateNewPassword(
  password: string,
  capability: AvailablePasswordChangeCapability
): PasswordValidationError | undefined {
  return getPasswordPolicyChecks(password, capability).find((check) => !check.satisfied)?.error;
}

export function validatePasswordChange(
  values: PasswordChangeValues,
  capability: PasswordChangeCapability
): PasswordFieldErrors {
  const errors: PasswordFieldErrors = validateNewPasswordPair(values, capability);

  if (!values.currentPassword) errors.currentPassword = "required";

  if (values.newPassword && values.currentPassword === values.newPassword && !errors.newPassword) {
    errors.newPassword = "password_unchanged";
  }

  return errors;
}

export type NewPasswordValues = Pick<PasswordChangeValues, "newPassword" | "confirmPassword">;
export type NewPasswordFieldErrors = Pick<PasswordFieldErrors, "newPassword" | "confirmPassword">;

export function newPasswordsMatch(values: NewPasswordValues): boolean {
  return values.newPassword.length > 0 && values.newPassword === values.confirmPassword;
}

/** Admin edits may leave both fields empty; setting a password always requires a matching pair. */
export function validateNewPasswordPair(
  values: NewPasswordValues,
  capability: PasswordChangeCapability,
  required = true
): NewPasswordFieldErrors {
  const errors: NewPasswordFieldErrors = {};
  if (!required && !values.newPassword && !values.confirmPassword) return errors;

  if (!values.newPassword) errors.newPassword = "required";
  if (!values.confirmPassword) errors.confirmPassword = "required";

  if (values.newPassword && values.confirmPassword && !newPasswordsMatch(values)) {
    errors.confirmPassword = "confirmation_mismatch";
  }

  if ((capability.source === "eneo" || capability.source === "zitadel") && values.newPassword) {
    const policyError = validateNewPassword(values.newPassword, capability);
    if (policyError) errors.newPassword = policyError;
  }

  return errors;
}

export function firstInvalidPasswordField(errors: PasswordFieldErrors): PasswordField | undefined {
  return (["currentPassword", "newPassword", "confirmPassword"] as const).find(
    (field) => errors[field] !== undefined
  );
}

export function isCurrentPasswordChangeDialogSubmission(
  dialogIsOpen: boolean,
  currentDialogEpoch: number,
  submittedInDialogEpoch: number
): boolean {
  return dialogIsOpen && currentDialogEpoch === submittedInDialogEpoch;
}
