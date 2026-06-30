"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import {
  ConfirmedPasswordField,
  isConfirmedPasswordValid
} from "@/components/composites/confirmed-password-field";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";

/**
 * Self-service password change (password accounts only; the backend rejects
 * federated/OIDC accounts). Requires the new password twice and checks the
 * match live so a typo can't lock the user out.
 */
export function ChangePasswordCard() {
  const t = useTranslations();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");

  const valid =
    current.length >= 7 &&
    next.length >= 7 &&
    isConfirmedPasswordValid({ value: next, confirmation: confirm, required: true });

  const change = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/users/me/change-password/", {
          body: { current_password: current, new_password: next }
        })
      ),
    onSuccess: () => {
      toast.success(t("password_changed"));
      setCurrent("");
      setNext("");
      setConfirm("");
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <SettingsGroup title={t("change_password")}>
      <SettingsRow title={t("change_password")} description={t("change_password_description")}>
        <form
          className="flex max-w-sm flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) change.mutate();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="current-password">{t("current_password")}</Label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(event) => setCurrent(event.target.value)}
            />
          </div>
          <ConfirmedPasswordField
            id="new-password"
            label={t("new_password")}
            confirmLabel={t("confirm_password")}
            value={next}
            confirmation={confirm}
            onValueChange={setNext}
            onConfirmationChange={setConfirm}
            errorMessage={t("passwords_do_not_match")}
            required
          />
          <Button type="submit" className="w-fit" disabled={!valid || change.isPending}>
            {change.isPending ? t("saving") : t("save")}
          </Button>
        </form>
      </SettingsRow>
    </SettingsGroup>
  );
}
