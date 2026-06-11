"use client";

import { useActionState } from "react";
import { useTranslations } from "next-intl";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { loginAction, type LoginFormState } from "./actions";

const ERROR_MESSAGE_KEYS: Record<NonNullable<LoginFormState["error"]>, string> = {
  invalid_credentials: "invalid_credentials",
  missing_fields: "invalid_credentials",
  deactivated: "access_disabled",
  unavailable: "login_failed"
};

export function LoginForm({ next }: { next?: string }) {
  const t = useTranslations();
  const [state, formAction, pending] = useActionState(loginAction, {});

  return (
    <form action={formAction} className="flex flex-col gap-4">
      {state.error && (
        <Alert variant="destructive">
          <AlertDescription>{t(ERROR_MESSAGE_KEYS[state.error])}</AlertDescription>
        </Alert>
      )}
      {next && <input type="hidden" name="next" value={next} />}
      <div className="flex flex-col gap-2">
        <Label htmlFor="email">{t("email")}</Label>
        <Input id="email" name="email" type="email" autoComplete="email" required />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="password">{t("password")}</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />
      </div>
      <Button type="submit" disabled={pending}>
        {t("login")}
      </Button>
    </form>
  );
}
