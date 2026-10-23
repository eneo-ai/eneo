"use client";

import { TextInput } from "@/components/astryx/text-input";
import { useState } from "react";

/** What is wrong with a secret and its confirmation, if anything. */
export type ConfirmedSecretProblem = "required" | "mismatch" | null;

/**
 * `required`: a required secret is empty. `mismatch`: the two entries differ,
 * including a secret without its confirmation.
 */
export function confirmedSecretProblem({
  value,
  confirmation,
  isRequired = false
}: {
  value: string;
  confirmation: string;
  isRequired?: boolean;
}): ConfirmedSecretProblem {
  if (value === "" && confirmation === "") return isRequired ? "required" : null;
  return value === confirmation ? null : "mismatch";
}

export type ConfirmedSecretInputProps = {
  label: string;
  confirmLabel: string;
  value: string;
  confirmation: string;
  onValueChange: (value: string) => void;
  onConfirmationChange: (value: string) => void;
  /** Shown under the first label (what the secret is for, how it is stored). */
  description?: string;
  /**
   * Ids of elements that describe both fields, such as a password policy
   * checklist (PasswordPolicyChecklist), read after their own texts.
   */
  describedBy?: string;
  isRequired?: boolean;
  isDisabled?: boolean;
  /** Password managers read it: "new-password" (default), "off" for API keys. */
  autoComplete?: string;
  placeholder?: string;
  /** At the first field when a required secret is empty and `showErrors` is set. */
  requiredMessage?: string;
  /**
   * What is wrong with the secret itself (a rule it breaks, a server's
   * refusal), at the first field. The caller decides when it shows.
   */
  valueError?: string;
  /** At the confirmation when the two differ: how to fix it. */
  mismatchMessage: string;
  /**
   * The form was submitted: show every problem. Before that, only a mismatch
   * shows, once the confirmation has been left.
   */
  showErrors?: boolean;
  valueRef?: React.Ref<HTMLInputElement>;
  confirmationRef?: React.Ref<HTMLInputElement>;
};

/**
 * A secret (password, API key, client secret) typed twice so a typo is not
 * saved: two Astryx password fields with their labels, an optional
 * description, and the problem as text at the field it concerns. Paste and
 * password managers work as in any password field.
 *
 * The mismatch waits until the confirmation has been left (or the form was
 * submitted): shown on the first keystroke, it would be announced, as an
 * error, before the user had finished typing.
 *
 * @example
 * <ConfirmedSecretInput
 *   label={t("api_key")}
 *   confirmLabel={t("confirm_api_key")}
 *   value={key}
 *   confirmation={confirmation}
 *   onValueChange={setKey}
 *   onConfirmationChange={setConfirmation}
 *   autoComplete="off"
 *   isRequired
 *   requiredMessage={t("provider_form_api_key_required")}
 *   mismatchMessage={t("provider_form_secret_mismatch")}
 *   showErrors={submitted}
 * />
 */
export function ConfirmedSecretInput({
  label,
  confirmLabel,
  value,
  confirmation,
  onValueChange,
  onConfirmationChange,
  description,
  describedBy,
  isRequired = false,
  isDisabled = false,
  autoComplete = "new-password",
  placeholder,
  requiredMessage,
  valueError,
  mismatchMessage,
  showErrors = false,
  valueRef,
  confirmationRef
}: ConfirmedSecretInputProps) {
  const [confirmationLeft, setConfirmationLeft] = useState(false);
  const problem = confirmedSecretProblem({ value, confirmation, isRequired });
  const valueMessage =
    showErrors && problem === "required" && requiredMessage ? requiredMessage : valueError;
  const showMismatch = problem === "mismatch" && (showErrors || confirmationLeft);

  return (
    <div className="flex flex-col gap-3">
      <TextInput
        ref={valueRef}
        type="password"
        label={label}
        description={description}
        aria-describedby={describedBy}
        value={value}
        onChange={onValueChange}
        isRequired={isRequired}
        isDisabled={isDisabled}
        autoComplete={autoComplete}
        placeholder={placeholder}
        status={valueMessage ? { type: "error", message: valueMessage } : undefined}
      />
      <TextInput
        ref={confirmationRef}
        type="password"
        label={confirmLabel}
        aria-describedby={describedBy}
        value={confirmation}
        onChange={onConfirmationChange}
        // Required whenever there is a secret to confirm.
        isRequired={isRequired || value !== ""}
        isDisabled={isDisabled}
        autoComplete={autoComplete}
        onBlur={() => {
          if (confirmation !== "") setConfirmationLeft(true);
        }}
        status={showMismatch ? { type: "error", message: mismatchMessage } : undefined}
      />
    </div>
  );
}
