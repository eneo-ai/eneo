import { useTranslations } from "use-intl";
import { QuietBanner } from "@/components/astryx/banner";
import { loginDiagnosticMessageKey, type LoginDiagnostics } from "@/lib/auth/login-diagnostics";

export function LoginDiagnosticsAlert({ diagnostics }: { diagnostics: LoginDiagnostics }) {
  const t = useTranslations();
  return (
    <QuietBanner
      status="error"
      title={t("authentication_failed")}
      description={t(loginDiagnosticMessageKey(diagnostics))}
    >
      <div className="flex flex-col gap-2 text-xs [overflow-wrap:anywhere]">
        {diagnostics.rawDetail ? (
          <p>{t("oidc_error_detail", { detail: diagnostics.rawDetail })}</p>
        ) : null}
        {diagnostics.info ? <code>{diagnostics.info}</code> : null}
        {diagnostics.correlation ? (
          <p>
            {t("oidc_correlation_hint")}
            <code>{diagnostics.correlation}</code>
          </p>
        ) : null}
      </div>
    </QuietBanner>
  );
}
