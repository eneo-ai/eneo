"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
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

  const mismatch = confirm.length > 0 && confirm !== next;
  const valid = current.length >= 7 && next.length >= 7 && confirm === next;

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
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="new-password">{t("new_password")}</Label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(event) => setNext(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="confirm-password">{t("confirm_password")}</Label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              aria-invalid={mismatch}
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
            />
            {mismatch && (
              <p className="text-xs text-red-600 dark:text-red-400" aria-live="polite">
                {t("passwords_do_not_match")}
              </p>
            )}
          </div>
          <Button type="submit" className="w-fit" disabled={!valid || change.isPending}>
            {change.isPending ? t("saving") : t("save")}
          </Button>
        </form>
      </SettingsRow>
    </SettingsGroup>
  );
}
