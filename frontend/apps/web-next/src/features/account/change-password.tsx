"use client";

import { Button } from "@astryxdesign/core/Button";
import { FormLayout } from "@astryxdesign/core/FormLayout";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@/components/astryx/text-input";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { revealProblems } from "@/components/composites/field-problem";
import { ConfirmedSecretInput } from "@/components/composites/confirmed-secret-input";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { passwordChangedLogoutUrl } from "@/lib/auth/password-change-path";
import {
  newPasswordErrors,
  passwordCapability,
  type PasswordPolicy
} from "@/features/auth/password-policy";
import { PasswordPolicyChecklist } from "@/features/auth/password-policy-checklist";

type Field = "current" | "next" | "confirm";

/** What the backend refused, said at the field it concerns. */
type ServerErrors = Partial<Record<"current" | "next", string>>;

export function ChangePasswordForm({
  policy,
  email,
  currentPasswordHint,
  afterChangeHref = passwordChangedLogoutUrl(null)
}: {
  policy: PasswordPolicy;
  email: string;
  /** Under the current-password field, e.g. "enter the one-time password". */
  currentPasswordHint?: string;
  /** Where the browser goes once the password is changed; signs out by default. */
  afterChangeHref?: string;
}) {
  const t = useTranslations();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<ServerErrors>({});
  const currentRef = useRef<HTMLInputElement>(null);
  const nextRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const checklistId = useId();
  const fieldRef = (field: Field) =>
    ({ current: currentRef, next: nextRef, confirm: confirmRef })[field].current;

  const pair = newPasswordErrors(t, { password: next, confirmation: confirm, policy });
  const errors: Record<Field, string | undefined> = {
    current: current ? serverErrors.current : t("change_password_current_required"),
    next: pair.password ?? (next === current ? t("password_must_be_different") : serverErrors.next),
    confirm: pair.confirmation
  };
  // Server refusals show at once; the rest once the form was submitted.
  const shown = (field: Field) =>
    submitted || (field !== "confirm" && serverErrors[field]) ? errors[field] : undefined;
  const currentError = shown("current");

  const change = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/users/me/password/", {
          body: { current_password: current, new_password: next }
        })
      ),
    onSuccess: () => {
      // The change bumps the credential version, so the session is gone: the
      // logout route tells the login page the password was changed (a toast
      // would not survive the navigation).
      window.location.assign(afterChangeHref);
    },
    onError: (error) => {
      const code = error instanceof EneoApiError ? error.code : undefined;
      const status = error instanceof EneoApiError ? error.status : undefined;
      const atField: ServerErrors | null =
        code === 9061
          ? { current: t("current_password_incorrect") }
          : code === 9058
            ? { next: t("password_must_be_different") }
            : code === 9059
              ? { next: t("password_policy_rejected") }
              : null;
      if (atField) {
        revealProblems(
          () => setServerErrors(atField),
          fieldRef(atField.current ? "current" : "next")
        );
      } else if (status === 429) {
        // The rate limit answers without a code of its own.
        toast.error(t("password_change_rate_limited"));
      } else {
        // 9060 (no local password to change) is mapped like any other code.
        toastApiError(error, t);
      }
    }
  });

  return (
    <form
      className="max-w-sm"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (change.isPending) return;
        if (Object.values(errors).some(Boolean)) {
          const first = (["current", "next", "confirm"] as const).find((field) => errors[field]);
          revealProblems(() => setSubmitted(true), first && fieldRef(first));
          return;
        }
        change.mutate();
      }}
    >
      {/* Every field is required, the default and unmarked (decision 40). */}
      <FormLayout defaultOptionality="required" className="gap-3">
        {/* Read by password managers only, to match the change to the saved
          login (the login form's `username` is the email): out of the tab
          order and hidden from assistive technology, but not display:none,
          which some managers skip. */}
        <input
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          name="username"
          autoComplete="username"
          value={email}
          readOnly
        />
        <TextInput
          ref={currentRef}
          type="password"
          label={t("current_password")}
          value={current}
          onChange={(value) => {
            setCurrent(value);
            setServerErrors((refused) => ({ ...refused, current: undefined }));
          }}
          autoComplete="current-password"
          description={currentPasswordHint}
          isRequired
          status={currentError ? { type: "error", message: currentError } : undefined}
        />
        <PasswordPolicyChecklist
          id={checklistId}
          password={next}
          confirmation={confirm}
          policy={policy}
        />
        <ConfirmedSecretInput
          label={t("new_password")}
          confirmLabel={t("confirm_password")}
          describedBy={checklistId}
          value={next}
          confirmation={confirm}
          onValueChange={(value) => {
            setNext(value);
            setServerErrors((refused) => ({ ...refused, next: undefined }));
          }}
          onConfirmationChange={setConfirm}
          // Password managers offer a generated password and fill both.
          autoComplete="new-password"
          isRequired
          valueError={shown("next")}
          mismatchMessage={errors.confirm ?? t("change_password_mismatch")}
          showErrors={submitted}
          valueRef={nextRef}
          confirmationRef={confirmRef}
        />
        <Text type="supporting">{t("password_change_sign_out_notice")}</Text>
        <Button
          type="submit"
          variant="primary"
          label={t("save")}
          className="self-start"
          // Keeps focus while saving; a second press is ignored above.
          isLoading={change.isPending}
          isInterruptible
        />
      </FormLayout>
    </form>
  );
}

/**
 * Self-service password change for Eneo's own passwords, under the policy the
 * backend enforces (`password_change` on the signed-in user). A password
 * managed by an identity provider is changed there instead.
 *
 * Problems show at their fields on submit, and focus moves to the first
 * (WCAG 3.3.1); what the backend refuses (a wrong current password, a reused
 * one) shows at its field too. Password managers get what they need to
 * update the saved login.
 */
export function ChangePasswordCard() {
  const t = useTranslations();
  const { user } = useAppContext();
  const capability = passwordCapability(user.password_change);

  return (
    <SettingsGroup title={t("change_password")} tour="account-password">
      <SettingsRow
        title={t("change_password")}
        description={
          capability.source === "eneo"
            ? t("password_settings_description")
            : capability.source === "external"
              ? t("password_managed_externally")
              : t("password_capability_unavailable")
        }
      >
        {capability.source === "eneo" ? (
          <ChangePasswordForm policy={capability.policy} email={user.email} />
        ) : null}
      </SettingsRow>
    </SettingsGroup>
  );
}
