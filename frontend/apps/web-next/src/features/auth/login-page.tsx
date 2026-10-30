import { Button } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useTranslations } from "use-intl";
import { z } from "zod";
import { Banner } from "@astryxdesign/core/Banner";
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
import { FederationPending } from "./federation-pending";

export const loginSearch = z.object({
  next: z.string().optional(),
  error: z.string().optional(),
  message: z.string().optional(),
  info: z.string().optional(),
  detailCode: z.string().optional(),
  correlation: z.string().optional(),
  rawDetail: z.string().optional(),
  // Keep invalid input present in the flat URL serializer. Dropping the key
  // would turn a bad tenant link into an automatic or remembered login.
  tenant: z
    .string()
    .regex(/^[a-z0-9-]+$/)
    .catch("")
    .optional(),
  showUsernameAndPassword: z.string().catch("").optional()
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
  // A failed discovery already exposed the form. Retrying must not discard
  // credentials the user has since entered by starting SSO automatically.
  const showCredentials =
    search.showUsernameAndPassword !== undefined || federation.errorUpdatedAt > 0;
  const suppressAuto =
    showCredentials ||
    search.message !== undefined ||
    search.error !== undefined ||
    search.detailCode !== undefined;
  const autoSso = !bound && !suppressAuto && search.tenant === undefined ? ssoHref : null;
  const ssoStarted = useRef(false);
  useEffect(() => {
    if (autoSso && !ssoStarted.current) {
      ssoStarted.current = true;
      navigateTo(autoSso);
    }
  }, [autoSso]);
  const credentialSearch = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value != null && key !== "showUsernameAndPassword")
      credentialSearch.set(key, key === "next" ? safeNextPath(value) : value);
  }
  if (!showCredentials) credentialSearch.set("showUsernameAndPassword", "true");
  const credentialHref = `/login${credentialSearch.size ? `?${credentialSearch}` : ""}`;
  const enteringTenant =
    federation.data?.has_multi_tenant_federation && search.tenant && !suppressAuto;

  return (
    <PublicPage
      title={t("login")}
      description={t("login_description")}
      accessibilityStatementUrl={accessibilityStatementUrl}
    >
      {bound && (me.isPending || me.data) ? (
        <LoadingState rows={1} label={t("redirecting")} />
      ) : autoSso ? (
        <FederationPending href={autoSso} />
      ) : (
        <>
          {diagnostics ? <LoginDiagnosticsAlert diagnostics={diagnostics} /> : null}
          {notice ? <Banner status="info" title={t(notice)} /> : null}
          <QueryStateBoundary
            query={federation}
            rows={1}
            errorTitle={t("login_options_unavailable")}
          >
            {() => (
              <>
                {federation.data?.has_multi_tenant_federation ? (
                  <TenantFederationLogin
                    next={search.next}
                    tenant={search.tenant}
                    suppressAuto={suppressAuto}
                    failed={diagnostics !== null}
                  />
                ) : ssoHref ? (
                  <Button label={t("login_with_sso")} href={ssoHref} as={DocumentLink} />
                ) : null}
                {showCredentials && ssoHref ? (
                  <p className="text-ax-text-secondary text-center text-xs uppercase">{t("or")}</p>
                ) : null}
              </>
            )}
          </QueryStateBoundary>
          {(showCredentials || (!federation.isPending && !ssoHref && !enteringTenant)) && (
            <LoginForm next={search.next} />
          )}
          {ssoHref ? (
            <Button
              as={DocumentLink}
              href={credentialHref}
              variant="ghost"
              label={t(showCredentials ? "hide_login_fields" : "show_login_fields")}
            />
          ) : null}
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
