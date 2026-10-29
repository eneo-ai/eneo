import { Button } from "@astryxdesign/core/Button";
import { useActionState, useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { QuietBanner } from "@/components/astryx/banner";
import { PasswordInput } from "@/components/astryx/password-input";
import { TextInput } from "@/components/astryx/text-input";
import { submitPasswordLogin, type LoginFormState } from "./password-login";

const ERROR_KEYS: Record<NonNullable<LoginFormState["error"]>, string> = {
  invalid_credentials: "invalid_credentials",
  missing_fields: "invalid_credentials",
  too_many_attempts: "login_too_many_attempts_later",
  deactivated: "login_account_deactivated",
  unavailable: "login_failed"
};

export function LoginForm({ next }: { next?: string }) {
  const t = useTranslations();
  const [state, action, pending] = useActionState(submitPasswordLogin.bind(null, next), {});
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const errorRef = useRef<HTMLDivElement>(null);
  const errorId = useId();
  const minutes =
    state.retryAfterSeconds == null ? null : Math.max(1, Math.ceil(state.retryAfterSeconds / 60));
  const blocked =
    state.error === "too_many_attempts" ||
    (state.error === "invalid_credentials" && state.attemptsRemaining === 0 && minutes !== null);
  const rejected = state.error === "invalid_credentials" || state.error === "missing_fields";
  const attempts =
    state.error === "invalid_credentials" && !blocked ? state.attemptsRemaining : null;

  useEffect(() => {
    if (state.error) errorRef.current?.focus();
  }, [state]);

  return (
    <form
      action={action}
      onSubmit={(event) => {
        if (pending) event.preventDefault();
      }}
      className="flex flex-col gap-4"
    >
      {state.error ? (
        <div id={errorId} ref={errorRef} tabIndex={-1}>
          <QuietBanner
            status="error"
            title={
              blocked
                ? minutes !== null
                  ? t("login_too_many_attempts", { minutes })
                  : t("login_too_many_attempts_later")
                : t(ERROR_KEYS[state.error])
            }
            description={
              attempts != null ? t("login_attempts_remaining", { count: attempts }) : undefined
            }
          />
        </div>
      ) : null}
      <TextInput
        label={t("email")}
        htmlName="email"
        type="email"
        autoComplete="username"
        value={email}
        onChange={setEmail}
        isRequired
        aria-invalid={rejected || undefined}
        aria-describedby={rejected ? errorId : undefined}
      />
      <PasswordInput
        label={t("password")}
        htmlName="password"
        autoComplete="current-password"
        value={password}
        onChange={setPassword}
        isRequired
        aria-invalid={rejected || undefined}
        aria-describedby={rejected ? errorId : undefined}
      />
      <Button
        type="submit"
        variant="primary"
        label={t("login")}
        isLoading={pending}
        isInterruptible
      />
    </form>
  );
}
