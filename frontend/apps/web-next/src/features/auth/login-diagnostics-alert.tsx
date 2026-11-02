import { useTranslations } from "use-intl";
import { Button } from "@astryxdesign/core/Button";
import { QuietBanner } from "@/components/astryx/banner";
import { loginDiagnosticMessageKey, type LoginDiagnostics } from "@/lib/auth/login-diagnostics";
import { useCopy } from "@/lib/hooks/use-copy";

/** The reference support asks for after a failed sign-in, with a button that copies it. */
export function CorrelationReference({ id }: { id: string }) {
  const t = useTranslations();
  const { copy, isCopied } = useCopy();
  return (
    <div className="flex flex-col items-start gap-2 text-xs [overflow-wrap:anywhere]">
      <p>
        {t("oidc_correlation_hint")}
        <code>{id}</code>
      </p>
      <Button
        label={t(isCopied ? "copied" : "copy_correlation_id")}
        variant="secondary"
        onClick={() => {
          void copy(id);
        }}
      />
    </div>
  );
}

export function LoginDiagnosticsAlert({ diagnostics }: { diagnostics: LoginDiagnostics }) {
  const t = useTranslations();
  return (
    <QuietBanner
      status="error"
      title={t("authentication_failed")}
      description={t(loginDiagnosticMessageKey(diagnostics))}
      collapsible={false}
    >
      <div className="flex flex-col gap-2 text-xs [overflow-wrap:anywhere]">
        {diagnostics.rawDetail ? (
          <p>{t("oidc_error_detail", { detail: diagnostics.rawDetail })}</p>
        ) : null}
        {diagnostics.info ? <code>{diagnostics.info}</code> : null}
        {diagnostics.correlation ? <CorrelationReference id={diagnostics.correlation} /> : null}
      </div>
    </QuietBanner>
  );
}
