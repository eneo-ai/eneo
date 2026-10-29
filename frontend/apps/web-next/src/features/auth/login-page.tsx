import { Button } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useTranslations } from "use-intl";
import { z } from "zod";
import { QuietBanner } from "@/components/astryx/banner";
import { LoadingState } from "@/components/composites/loading-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { getSessionSnapshot } from "@/lib/api/refusal";
import { sessionQueries } from "@/lib/api/session";
import { loginDiagnosticsFromRecord } from "@/lib/auth/login-diagnostics";
import { safeNextPath } from "@/lib/auth/safe-next";
import { navigateTo } from "@/lib/navigate-to";
import { LoginDiagnosticsAlert } from "./login-diagnostics-alert";
import { LoginForm } from "./login-form";
import { PublicPage } from "./public-page";
import { ssoEntry } from "./sso-entry";
import { TenantFederationLogin } from "./tenant-federation-login";
import { DocumentLink } from "./document-link";

export const loginSearch = z.object({
  next: z.string().optional(),
  error: z.string().optional(),
  message: z.string().optional(),
  info: z.string().optional(),
  detailCode: z.string().optional(),
  correlation: z.string().optional(),
  rawDetail: z.string().optional()
});

type Props = { search: z.infer<typeof loginSearch>; accessibilityStatementUrl: string | null };
const notices = new Map([
  ["expired", "session_expired_please_login_again"],
  ["logout", "logout_success"],
  ["password_changed", "password_changed_login_again"]
]);

export function LoginPage({ search, accessibilityStatementUrl }: Props) {
  const t = useTranslations();
  const session = getSessionSnapshot();
  // Boot binds the document once. An anonymous document must never adopt a
  // later cookie by issuing another headerless /me probe.
  const bound = session.status === "bound" && session.generation !== null;
  const queries = sessionQueries(browserApi);
  const me = useQuery({ ...queries.me, enabled: bound });
  const federation = useQuery(queries.federationStatus);
  const continued = useRef(false);
  useEffect(() => {
    if (bound && me.data && !continued.current) {
      continued.current = true;
      navigateTo(safeNextPath(search.next), { replace: true });
    }
  }, [bound, me.data, search.next]);
  const diagnostics = loginDiagnosticsFromRecord(search);
  const ssoHref = ssoEntry(federation.data, search.next);
  const notice = search.message ? notices.get(search.message) : undefined;

  return (
    <PublicPage
      title={t("login")}
      description={t("login_description")}
      accessibilityStatementUrl={accessibilityStatementUrl}
    >
      {bound && (me.isPending || me.data) ? (
        <LoadingState rows={1} label={t("redirecting")} />
      ) : (
        <>
          {diagnostics ? <LoginDiagnosticsAlert diagnostics={diagnostics} /> : null}
          {notice ? <QuietBanner status="info" title={t(notice)} /> : null}
          <QueryStateBoundary
            query={federation}
            rows={1}
            errorTitle={t("login_options_unavailable")}
          >
            {() => (
              <>
                {federation.data?.has_multi_tenant_federation ? (
                  <TenantFederationLogin next={search.next} />
                ) : ssoHref ? (
                  <Button label={t("login_with_sso")} href={ssoHref} as={DocumentLink} />
                ) : null}
                {ssoHref || federation.data?.has_multi_tenant_federation ? (
                  <p className="text-ax-text-secondary text-center text-xs uppercase">{t("or")}</p>
                ) : null}
              </>
            )}
          </QueryStateBoundary>
          <LoginForm next={search.next} />
        </>
      )}
    </PublicPage>
  );
}

export function LoginFailedPage({ search, accessibilityStatementUrl }: Props) {
  const t = useTranslations();
  const diagnostics = loginDiagnosticsFromRecord(search);
  const retry = search.next
    ? `/login?${new URLSearchParams({ next: safeNextPath(search.next) })}`
    : "/login";
  return (
    <PublicPage title={t("login_failed")} accessibilityStatementUrl={accessibilityStatementUrl}>
      {diagnostics ? (
        <LoginDiagnosticsAlert diagnostics={diagnostics} />
      ) : (
        <p className="text-ax-text-secondary text-sm">{t("failed_to_login")}</p>
      )}
      <Button label={t("try_logging_in_again")} href={retry} as={DocumentLink} />
    </PublicPage>
  );
}
