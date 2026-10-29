import { Button } from "@astryxdesign/core/Button";
import { queryOptions, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { navigateTo } from "@/lib/navigate-to";
import { federationHref } from "./sso-entry";
import { DocumentLink } from "./document-link";

const LAST_TENANT_KEY = "eneo-last-tenant-slug";
const tenantsQuery = queryOptions({
  queryKey: ["auth", "tenants"],
  queryFn: () => unwrap(browserApi.GET("/api/v1/auth/tenants")),
  staleTime: Infinity,
  refetchOnWindowFocus: false
});

function rememberedSlug(): string | null {
  try {
    return sessionStorage.getItem(LAST_TENANT_KEY);
  } catch {
    return null;
  }
}

function remember(slug: string): void {
  // A storage restriction must not prevent authentication.
  try {
    sessionStorage.setItem(LAST_TENANT_KEY, slug);
  } catch {
    /* The choice simply won't be remembered. */
  }
}

export function TenantFederationLogin({ next }: { next?: string }) {
  const t = useTranslations();
  const query = useQuery(tenantsQuery);
  return (
    <QueryStateBoundary
      query={query}
      rows={2}
      loadingLabel={t("loading_organizations")}
      errorTitle={t("failed_to_load_organizations")}
    >
      {(data) => <TenantChoices tenants={data.tenants} next={next} />}
    </QueryStateBoundary>
  );
}

function TenantChoices({ tenants, next }: { tenants: Schema<"TenantInfo">[]; next?: string }) {
  const t = useTranslations();
  const [remembered] = useState(rememberedSlug);
  const [showSelector, setShowSelector] = useState(false);
  const started = useRef(false);
  const previous = tenants.find((tenant) => tenant.slug === remembered);
  const onlyTenant = tenants.length === 1 ? tenants[0] : undefined;

  useEffect(() => {
    if (onlyTenant && !previous && !started.current) {
      started.current = true;
      remember(onlyTenant.slug);
      navigateTo(federationHref(next, onlyTenant.slug));
    }
  }, [onlyTenant, previous, next]);

  return (
    <div className="flex flex-col gap-2">
      {previous && !showSelector ? (
        <>
          <Button
            label={`${t("continue")} · ${previous.display_name || previous.name}`}
            href={federationHref(next, previous.slug)}
            as={DocumentLink}
            onClick={() => remember(previous.slug)}
          />
          <Button
            label={t("oidc_choose_another_org")}
            variant="ghost"
            onClick={() => setShowSelector(true)}
          />
        </>
      ) : tenants.length === 0 ? (
        <p className="text-ax-text-secondary text-center text-sm">
          {t("no_organizations_available")}
        </p>
      ) : (
        <>
          <p className="text-ax-text-secondary text-center text-sm">
            {t("select_your_organization")}
          </p>
          <div className="grid max-h-64 gap-2 overflow-y-auto">
            {tenants.map((tenant) => (
              <Button
                key={tenant.slug}
                label={tenant.display_name || tenant.name}
                href={federationHref(next, tenant.slug)}
                as={DocumentLink}
                onClick={() => remember(tenant.slug)}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
