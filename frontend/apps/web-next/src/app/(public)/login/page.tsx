import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { loginDiagnosticsFromRecord } from "@/lib/auth/login-diagnostics";
import { isOidcEnabled } from "@/lib/auth/oidc";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
import { getSession } from "@/lib/auth/session";
import { env } from "@/lib/env";
import type { Schema } from "@/lib/api/models";
import { pageTitle } from "@/lib/page-metadata";
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

async function getSingleTenantFederationHref(): Promise<string | null> {
  try {
    const response = await fetch(`${env.ENEO_BACKEND_URL}/api/v1/auth/initiate`, {
      headers: { accept: "application/json" },
      cache: "no-store"
    });
    if (!response.ok) return null;
    const body = (await response.json()) as Schema<"InitiateAuthResponse">;
    return body.authorization_url;
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
  if (await getSession()) redirect(DEFAULT_LANDING);

  const search = await searchParams;
  const { next, message } = search;
  const diagnostics = loginDiagnosticsFromRecord(search);
  const federationStatus = await getFederationStatus();
  const multiTenantFederation = federationStatus?.has_multi_tenant_federation === true;
  const singleTenantFederationHref =
    !multiTenantFederation && federationStatus?.has_single_tenant_federation === true
      ? await getSingleTenantFederationHref()
      : null;
  const t = await getTranslations();
  const oidc = !multiTenantFederation && (isOidcEnabled() || Boolean(singleTenantFederationHref));

  const loginHref =
    singleTenantFederationHref ??
    (next ? `/auth/login?next=${encodeURIComponent(next)}` : "/auth/login");

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">{t("welcome")}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
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
          {multiTenantFederation ? (
            <>
              <TenantFederationLogin />
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
          <LoginForm next={next} />
        </CardContent>
      </Card>
    </main>
  );
}
