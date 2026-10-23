import { Alert, AlertDescription } from "@/components/ui/alert";
import type { LoginDiagnostics } from "@/lib/auth/login-diagnostics";
import { loginDiagnosticMessageKey } from "@/lib/auth/login-diagnostics";

type Translate = (key: string, values?: Record<string, string>) => string;

export function LoginDiagnosticsAlert({
  diagnostics,
  t
}: {
  diagnostics: LoginDiagnostics;
  t: Translate;
}) {
  return (
    <Alert variant="destructive">
      <AlertDescription className="flex flex-col gap-2">
        <strong>{t("authentication_failed")}</strong>
        <span>{t(loginDiagnosticMessageKey(diagnostics))}</span>
        {diagnostics.rawDetail && (
          <span className="text-xs">
            {t("oidc_error_detail", { detail: diagnostics.rawDetail })}
          </span>
        )}
        {diagnostics.info && (
          <span className="text-muted-foreground text-xs">
            <code>{diagnostics.info}</code>
          </span>
        )}
        {diagnostics.correlation && (
          <span className="text-muted-foreground text-xs">
            {t("oidc_correlation_hint")}
            <code>{diagnostics.correlation}</code>
          </span>
        )}
      </AlertDescription>
    </Alert>
  );
}
