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

export type PasswordField = "currentPassword" | "newPassword" | "confirmPassword";

export type PasswordValidationError =
  | "required"
  | "current_password_incorrect"
  | "confirmation_mismatch"
  | "password_unchanged"
  | "policy_rejected"
  | "too_short"
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

// Frontend/admin hint only. Backend enforcement and the self-user capability are canonical.
export const ENEO_PASSWORD_POLICY = Object.freeze({
  minLength: 15,
  maxBytes: 72,
  requiresUppercase: false,
  requiresLowercase: false,
  requiresNumber: false,
  requiresSymbol: false
} satisfies PasswordPolicy);

export function validateNewPassword(
  password: string,
  policy: PasswordPolicy
): PasswordValidationError | undefined {
  const length = [...password].length;

  if (length < policy.minLength) return "too_short";
  if (policy.maxBytes !== null && new TextEncoder().encode(password).byteLength > policy.maxBytes) {
    return "too_long_bytes";
  }
  if (policy.requiresUppercase && !/\p{Lu}/u.test(password)) return "uppercase_required";
  if (policy.requiresLowercase && !/\p{Ll}/u.test(password)) return "lowercase_required";
  if (policy.requiresNumber && !/\p{N}/u.test(password)) return "number_required";
  if (policy.requiresSymbol && !/[^\p{L}\p{N}\s]/u.test(password)) return "symbol_required";
  return undefined;
}

export function validatePasswordChange(
  values: PasswordChangeValues,
  capability: PasswordChangeCapability
): PasswordFieldErrors {
  const errors: PasswordFieldErrors = {};

  if (!values.currentPassword) errors.currentPassword = "required";
  if (!values.newPassword) errors.newPassword = "required";
  if (!values.confirmPassword) errors.confirmPassword = "required";

  if (values.newPassword && values.currentPassword === values.newPassword) {
    errors.newPassword = "password_unchanged";
  }

  if (
    values.newPassword &&
    values.confirmPassword &&
    values.confirmPassword !== values.newPassword
  ) {
    errors.confirmPassword = "confirmation_mismatch";
  }

  if (capability.policy && values.newPassword) {
    const policyError = validateNewPassword(values.newPassword, capability.policy);
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
