import { Button } from "@astryxdesign/core/Button";
import { queryOptions, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslations } from "use-intl";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { useFocusRescue } from "@/lib/focus-rescue";
import { navigateTo } from "@/lib/navigate-to";
import { replaceUrl, useSearchParams } from "@/lib/navigation";
import { federationHref } from "./sso-entry";
import { DocumentLink } from "./document-link";
import { FederationPending } from "./federation-pending";

const LAST_TENANT_KEY = "eneo-last-tenant-slug";
const tenantsQuery = queryOptions({
  queryKey: ["auth", "tenants"],
  queryFn: () => unwrap(browserApi.GET("/api/v1/auth/tenants")),
  staleTime: Infinity,
  refetchOnWindowFocus: false
});

function rememberedTenant() {
  try {
    return { available: true, slug: sessionStorage.getItem(LAST_TENANT_KEY) };
  } catch {
    return { available: false, slug: null };
  }
}

function remember(slug: string): boolean {
  try {
    sessionStorage.setItem(LAST_TENANT_KEY, slug);
    return true;
  } catch {
    return false;
  }
}

export function TenantFederationLogin({
  next,
  tenant,
  suppressAuto,
  failed,
  children
}: {
  next?: string;
  tenant?: string;
  suppressAuto: boolean;
  failed: boolean;
  children?: ReactNode;
}) {
  const t = useTranslations();
  const [remembered] = useState(rememberedTenant);
  const search = useSearchParams();
  const [showSelector, setShowSelector] = useState(false);
  const started = useRef(false);
  const selectorHeading = useRef<HTMLParagraphElement>(null);
  const rescueFocus = useFocusRescue();
  const explicit = tenant || undefined;
  const direct = explicit && !suppressAuto && !showSelector;
  const query = useQuery({ ...tenantsQuery, enabled: !direct });
  const tenants = query.data?.tenants ?? [];
  const previous = tenants.find((item) => item.slug === (explicit ?? remembered.slug));
  const onlyTenant = tenants.length === 1 ? tenants[0] : undefined;

  useEffect(() => {
    const candidate =
      explicit ??
      (tenant === undefined && !previous && remembered.available ? onlyTenant?.slug : undefined);
    if (candidate && !suppressAuto && !showSelector && !started.current) {
      started.current = true;
      // Without a remembered choice, a failed login would automatically start
      // again in the next document. Keep the explicit link usable instead.
      const saved = remember(candidate);
      if (explicit || saved) {
        const href = federationHref(next, candidate);
        navigateTo(href);
      }
    }
  }, [
    explicit,
    tenant,
    onlyTenant,
    previous,
    remembered.available,
    next,
    suppressAuto,
    showSelector
  ]);

  if (direct) return <FederationPending href={federationHref(next, explicit)} />;

  return (
    <>
      <QueryStateBoundary
        query={query}
        rows={2}
        loadingLabel={t("loading_organizations")}
        errorTitle={t("failed_to_load_organizations")}
      >
        {() => (
          <div className="flex flex-col gap-2">
            {previous && !showSelector && (tenant === undefined || explicit) ? (
              <>
                <Button
                  label={
                    failed
                      ? t("oidc_retry_login")
                      : `${t("continue")} · ${previous.display_name || previous.name}`
                  }
                  href={federationHref(next, previous.slug)}
                  as={DocumentLink}
                  onClick={() => remember(previous.slug)}
                />
                <Button
                  label={t("oidc_choose_another_org")}
                  variant="ghost"
                  onClick={() => {
                    try {
                      sessionStorage.removeItem(LAST_TENANT_KEY);
                    } catch {
                      /* The explicit selector still works when storage is blocked. */
                    }
                    rescueFocus(() => selectorHeading.current);
                    setShowSelector(true);
                    const params = new URLSearchParams(search.toString());
                    for (const key of [
                      "tenant",
                      "message",
                      "error",
                      "detailCode",
                      "correlation",
                      "rawDetail"
                    ])
                      params.delete(key);
                    replaceUrl(`/login${params.size ? `?${params}` : ""}`);
                  }}
                />
              </>
            ) : tenants.length === 0 ? (
              <p className="text-ax-text-secondary text-center text-sm">
                {t("no_organizations_available")}
              </p>
            ) : (
              <>
                <p
                  ref={selectorHeading}
                  tabIndex={-1}
                  className="text-ax-text-secondary text-center text-sm"
                >
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
        )}
      </QueryStateBoundary>
      {children}
    </>
  );
}
