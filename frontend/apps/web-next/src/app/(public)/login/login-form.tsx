"use client";

import { useActionState, useEffect, useId, useRef } from "react";
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

/**
 * Password login (ACCESSIBILITY.md → Forms): works with password managers
 * (`username` / `current-password`), keeps the typed e-mail address after a
 * failed attempt (React resets uncontrolled fields after a form action; the
 * action returns it as the field's default) and moves focus to the error.
 */
export function LoginForm({ next }: { next?: string }) {
  const t = useTranslations();
  const [state, formAction, pending] = useActionState(loginAction, {});
  const errorRef = useRef<HTMLDivElement>(null);
  const errorId = useId();
  const credentialsRejected =
    state.error === "invalid_credentials" || state.error === "missing_fields";

  // Every failed attempt (a new state object) moves focus to its message.
  useEffect(() => {
    if (state.error) errorRef.current?.focus();
  }, [state]);

  return (
    <form action={formAction} className="flex flex-col gap-4">
      {state.error && (
        <Alert ref={errorRef} id={errorId} tabIndex={-1} variant="destructive">
          <AlertDescription>{t(ERROR_MESSAGE_KEYS[state.error])}</AlertDescription>
        </Alert>
      )}
      {next && <input type="hidden" name="next" value={next} />}
      <div className="flex flex-col gap-2">
        <Label htmlFor="email">{t("email")}</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          defaultValue={state.email}
          aria-invalid={credentialsRejected || undefined}
          aria-describedby={credentialsRejected ? errorId : undefined}
          required
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="password">{t("password")}</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          aria-invalid={credentialsRejected || undefined}
          aria-describedby={credentialsRejected ? errorId : undefined}
          required
        />
      </div>
      <Button type="submit" disabled={pending}>
        {t("login")}
      </Button>
    </form>
  );
}
