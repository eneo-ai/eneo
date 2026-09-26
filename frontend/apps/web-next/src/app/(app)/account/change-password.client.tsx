"use client";

import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  ConfirmedSecretInput,
  confirmedSecretProblem
} from "@/components/composites/confirmed-secret-input";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import {
  brokenRule,
  passwordCapability,
  type PasswordPolicy,
  type PolicyRule
} from "./password-policy";

type Translate = ReturnType<typeof useTranslations>;

/** A rule in the words of the SvelteKit account dialog's checklist. */
function ruleText(t: Translate, rule: PolicyRule, policy: PasswordPolicy): string {
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

/** The rules a new password must meet, as sentences before the field. */
function requirements(t: Translate, policy: PasswordPolicy): string {
  const rules: PolicyRule[] = [
    "min_length",
    ...(policy.requiresUppercase ? (["uppercase"] as const) : []),
    ...(policy.requiresLowercase ? (["lowercase"] as const) : []),
    ...(policy.requiresNumber ? (["number"] as const) : []),
    ...(policy.requiresSymbol ? (["symbol"] as const) : [])
  ];
  // bcrypt's byte limit is left out, as in SvelteKit: it is checked on save.
  return rules.map((rule) => `${ruleText(t, rule, policy)}.`).join(" ");
}

type Field = "current" | "next" | "confirm";

/** What the backend refused, said at the field it concerns. */
type ServerErrors = Partial<Record<"current" | "next", string>>;

function ChangePasswordForm({ policy, email }: { policy: PasswordPolicy; email: string }) {
  const t = useTranslations();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [serverErrors, setServerErrors] = useState<ServerErrors>({});
  const currentRef = useRef<HTMLInputElement>(null);
  const nextRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);
  const focusField = (field: Field) =>
    ({ current: currentRef, next: nextRef, confirm: confirmRef })[field].current?.focus();

  const nextRule = next ? brokenRule(next, policy) : undefined;
  const errors: Record<Field, string | undefined> = {
    current: current ? serverErrors.current : t("change_password_current_required"),
    next: !next
      ? t("change_password_new_required")
      : nextRule
        ? ruleText(t, nextRule, policy)
        : next === current
          ? t("password_must_be_different")
          : serverErrors.next,
    confirm:
      confirmedSecretProblem({ value: next, confirmation: confirm, isRequired: true }) === null
        ? undefined
        : confirm
          ? t("change_password_mismatch")
          : t("change_password_confirm_required")
  };
  // Server refusals show at once; the rest once the form was submitted.
  const shown = (field: Field) =>
    submitted || (field !== "confirm" && serverErrors[field]) ? errors[field] : undefined;
  const currentError = shown("current");

  function focusFirst(problems: Record<Field, string | undefined>) {
    const field = (["current", "next", "confirm"] as const).find((name) => problems[name]);
    if (field) focusField(field);
  }

  const change = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/users/me/password/", {
          body: { current_password: current, new_password: next }
        })
      ),
    onSuccess: () => {
      toast.success(t("password_changed"));
      window.location.assign("/logout");
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
        flushSync(() => setServerErrors(atField));
        focusField(atField.current ? "current" : "next");
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
      className="flex max-w-sm flex-col gap-3"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        if (change.isPending) return;
        if (Object.values(errors).some(Boolean)) {
          // Rendered before focus moves, so the field is read with its error.
          flushSync(() => setSubmitted(true));
          focusFirst(errors);
          return;
        }
        change.mutate();
      }}
    >
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
        isRequired
        status={currentError ? { type: "error", message: currentError } : undefined}
      />
      <ConfirmedSecretInput
        label={t("new_password")}
        confirmLabel={t("confirm_password")}
        description={requirements(t, policy)}
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
