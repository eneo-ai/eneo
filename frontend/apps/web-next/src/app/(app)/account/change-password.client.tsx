"use client";

import { TextInput } from "@astryxdesign/core/TextInput";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import {
  ConfirmedSecretInput,
  confirmedSecretProblem
} from "@/components/composites/confirmed-secret-input";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";

const MIN_LENGTH = 7;

/**
 * Self-service password change (password accounts only; the backend rejects
 * federated/OIDC accounts). Requires the new password twice so a typo can't
 * lock the user out.
 *
 * Password managers get what they need to update the saved login: the
 * account's identifier beside the fields (the login form's `username` is the
 * email), `current-password` for the old one and `new-password` for both new
 * entries, so they can offer a generated password and fill the confirmation.
 */
export function ChangePasswordCard() {
  const t = useTranslations();
  const { user } = useAppContext();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");

  const valid =
    current.length >= MIN_LENGTH &&
    next.length >= MIN_LENGTH &&
    confirmedSecretProblem({ value: next, confirmation: confirm, isRequired: true }) === null;

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
    onError: (error) => toastApiError(error, t)
  });

  return (
    <SettingsGroup title={t("change_password")} tour="account-password">
      <SettingsRow title={t("change_password")} description={t("change_password_description")}>
        <form
          className="flex max-w-sm flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) change.mutate();
          }}
        >
          {/* Read by password managers only: out of the tab order and hidden
              from assistive technology, but not display:none, which some
              managers skip. */}
          <input
            className="sr-only"
            tabIndex={-1}
            aria-hidden="true"
            name="username"
            autoComplete="username"
            value={user.email}
            readOnly
          />
          <TextInput
            type="password"
            label={t("current_password")}
            value={current}
            onChange={setCurrent}
            autoComplete="current-password"
            isRequired
          />
          <ConfirmedSecretInput
            label={t("new_password")}
            confirmLabel={t("confirm_password")}
            description={t("password_needs_7_chars")}
            value={next}
            confirmation={confirm}
            onValueChange={setNext}
            onConfirmationChange={setConfirm}
            autoComplete="new-password"
            isRequired
            mismatchMessage={t("passwords_do_not_match")}
          />
          <Button type="submit" className="w-fit" disabled={!valid || change.isPending}>
            {change.isPending ? t("saving") : t("save")}
          </Button>
        </form>
      </SettingsRow>
    </SettingsGroup>
  );
}
