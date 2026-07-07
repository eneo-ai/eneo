"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { Schema } from "@/lib/api/models";

const LAST_TENANT_KEY = "eneo-last-tenant-slug";
const TENANT_SLUG_PATTERN = /^[a-z0-9-]+$/;

type TenantInfo = Schema<"TenantInfo">;

async function fetchTenants(): Promise<TenantInfo[]> {
  const response = await fetch("/api/auth/tenants", { headers: { accept: "application/json" } });
  if (!response.ok) throw new Error("Failed to load tenants");
  const body = (await response.json()) as { tenants?: TenantInfo[] };
  return body.tenants ?? [];
}

async function initiateTenant(slug: string): Promise<string> {
  const response = await fetch(`/api/auth/initiate?tenant=${encodeURIComponent(slug)}`, {
    headers: { accept: "application/json" }
  });
  if (!response.ok) throw new Error("Failed to initiate authentication");
  const body = (await response.json()) as { authorization_url?: string };
  if (!body.authorization_url) throw new Error("Missing authorization URL");
  return body.authorization_url;
}

export function TenantFederationLogin() {
  const t = useTranslations();
  const [tenants, setTenants] = useState<TenantInfo[]>([]);
  const [rememberedSlug, setRememberedSlug] = useState<string | null>(null);
  const [showSelector, setShowSelector] = useState(false);
  const [loading, setLoading] = useState(true);
  const [redirecting, setRedirecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const nextTenants = await fetchTenants();
        if (!active) return;
        setTenants(nextTenants);

        const remembered = sessionStorage.getItem(LAST_TENANT_KEY);
        const validRemembered =
          remembered &&
          TENANT_SLUG_PATTERN.test(remembered) &&
          nextTenants.some((tenant) => tenant.slug === remembered);

        const onlyTenant = nextTenants.length === 1 ? nextTenants[0] : null;
        if (onlyTenant && !validRemembered) {
          await beginTenantLogin(onlyTenant.slug);
          return;
        }

        setRememberedSlug(validRemembered ? remembered : null);
        setShowSelector(!validRemembered);
      } catch {
        if (active) setError(t("failed_to_load_organizations"));
      } finally {
        if (active) setLoading(false);
      }
    }

    void load();
    return () => {
      active = false;
    };
    // beginTenantLogin intentionally stays outside the dependency list; it
    // performs a terminal navigation and should not restart the loader effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [t]);

  async function beginTenantLogin(slug: string) {
    try {
      setError(null);
      setRedirecting(true);
      sessionStorage.setItem(LAST_TENANT_KEY, slug);
      window.location.href = await initiateTenant(slug);
    } catch {
      setRedirecting(false);
      setError(t("failed_to_start_authentication"));
    }
  }

  const rememberedTenant = rememberedSlug
    ? tenants.find((tenant) => tenant.slug === rememberedSlug)
    : null;

  if (loading || redirecting) {
    return (
      <p className="text-muted-foreground py-2 text-center text-sm">
        {redirecting ? t("redirecting_to_authentication") : t("loading_organizations")}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {rememberedTenant && !showSelector ? (
        <div className="flex flex-col gap-2">
          <Button type="button" onClick={() => void beginTenantLogin(rememberedTenant.slug)}>
            {t("continue")} · {rememberedTenant.display_name || rememberedTenant.name}
          </Button>
          <Button type="button" variant="ghost" onClick={() => setShowSelector(true)}>
            {t("oidc_choose_another_org")}
          </Button>
        </div>
      ) : tenants.length === 0 ? (
        <p className="text-muted-foreground text-center text-sm">
          {t("no_organizations_available")}
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-muted-foreground text-center text-sm">
            {t("select_your_organization")}
          </p>
          <div className="grid max-h-64 gap-2 overflow-y-auto">
            {tenants.map((tenant) => (
              <Button
                key={tenant.slug}
                type="button"
                variant="outline"
                className="h-auto justify-start py-3 text-left whitespace-normal"
                onClick={() => void beginTenantLogin(tenant.slug)}
              >
                <span className="flex min-w-0 flex-col items-start">
                  <span className="truncate font-medium">{tenant.display_name || tenant.name}</span>
                  <span className="text-muted-foreground text-xs">{tenant.name}</span>
                </span>
              </Button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
