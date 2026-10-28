import { getTranslations } from "next-intl/server";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { loginDiagnosticsFromRecord } from "@/lib/auth/login-diagnostics";
import { isOidcEnabled } from "@/lib/auth/oidc";
import { safeNextPath } from "@/lib/auth/safe-next";
import { getSession } from "@/lib/auth/session";
import { env } from "@/lib/env";
import type { Schema } from "@/lib/api/models";
import { pageTitle } from "@/lib/page-metadata";
import { PublicPage } from "../public-page";
import { ContinueSignedIn } from "./continue-signed-in";
import { LoginDiagnosticsAlert } from "./login-diagnostics-alert";
import { LoginForm } from "./login-form";
import { TenantFederationLogin } from "./tenant-federation-login";

export const generateMetadata = pageTitle("login");

async function getFederationStatus(): Promise<Schema<"FederationStatusResponse"> | null> {
  try {
    const response = await fetch(`${env.ENEO_BACKEND_URL}/api/v1/auth/federation-status`, {
      headers: { accept: "application/json" },
      cache: "no-store"
    });
    return response.ok ? ((await response.json()) as Schema<"FederationStatusResponse">) : null;
  } catch {
    return null;
  }
}

export default async function LoginPage({
  searchParams
}: {
  searchParams: Promise<{
    next?: string;
    error?: string;
    message?: string;
    info?: string;
    detailCode?: string;
    correlation?: string;
    rawDetail?: string;
  }>;
}) {
  const search = await searchParams;
  const { next, message } = search;
  // Signed in, here or by the login action: continue in a new document.
  if (await getSession()) {
    const t = await getTranslations();
    return (
      <PublicPage title={t("login")}>
        <ContinueSignedIn href={safeNextPath(next)} />
        <p className="text-center">{t("redirecting")}</p>
      </PublicPage>
    );
  }

  const diagnostics = loginDiagnosticsFromRecord(search);
  const federationStatus = await getFederationStatus();
  const multiTenantFederation = federationStatus?.has_multi_tenant_federation === true;
  const singleTenantFederationHref =
    !multiTenantFederation && federationStatus?.has_single_tenant_federation === true
      ? "/api/auth/initiate" + (next ? "?next=" + encodeURIComponent(next) : "")
      : null;
  const t = await getTranslations();
  const oidc = !multiTenantFederation && (isOidcEnabled() || Boolean(singleTenantFederationHref));

  const loginHref =
    singleTenantFederationHref ??
    (next ? `/auth/login?next=${encodeURIComponent(next)}` : "/auth/login");

  return (
    <PublicPage title={t("login")} description={t("login_description")}>
      {diagnostics && <LoginDiagnosticsAlert diagnostics={diagnostics} t={t} />}
      {message === "expired" && (
        <Alert>
          <AlertDescription>{t("session_expired_please_login_again")}</AlertDescription>
        </Alert>
      )}
      {message === "logout" && (
        <Alert>
          <AlertDescription>{t("logout_success")}</AlertDescription>
        </Alert>
      )}
      {message === "password_changed" && (
        <Alert>
          <AlertDescription>{t("password_changed_login_again")}</AlertDescription>
        </Alert>
      )}
      {multiTenantFederation ? (
        <>
          <TenantFederationLogin next={next} />
          <div className="text-muted-foreground text-center text-xs uppercase">{t("or")}</div>
        </>
      ) : oidc ? (
        <>
          <Button asChild variant="default">
            <a href={loginHref}>{t("login_with_sso")}</a>
          </Button>
          <div className="text-muted-foreground text-center text-xs uppercase">{t("or")}</div>
        </>
      ) : null}
      <LoginForm />
    </PublicPage>
  );
}
