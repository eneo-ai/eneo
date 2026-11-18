import { Button } from "@astryxdesign/core/Button";
import { queryOptions, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { TextInput } from "@/components/astryx/text-input";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useAnnounceChange } from "@/lib/hooks/use-announce-change";
import { navigateTo } from "@/lib/navigate-to";
import { replaceUrl, useSearchParams } from "@/lib/navigation";
import { federationHref } from "./sso-entry";
import { DocumentLink } from "./document-link";
import { FederationPending } from "./federation-pending";
import { forgetTenant, rememberedTenant, rememberTenant } from "./tenant-choice";

const tenantsQuery = queryOptions({
  queryKey: ["auth", "tenants"],
  queryFn: () => unwrap(browserApi.GET("/api/v1/auth/tenants")),
  staleTime: Infinity,
  refetchOnWindowFocus: false
});

export function TenantFederationLogin({
  next,
  tenant,
  suppressAuto,
  failed
}: {
  next?: string;
  tenant?: string;
  suppressAuto: boolean;
  failed: boolean;
}) {
  const t = useTranslations();
  const [remembered] = useState(rememberedTenant);
  const search = useSearchParams();
  const [showSelector, setShowSelector] = useState(false);
  const [filter, setFilter] = useState("");
  const started = useRef(false);
  const selectorHeading = useRef<HTMLParagraphElement>(null);
  const rescueFocus = useFocusRescue();
  const explicit = tenant || undefined;
  const direct = explicit && !suppressAuto && !showSelector;
  const explicitRecovery = failed && !showSelector ? explicit : undefined;
  const query = useQuery({ ...tenantsQuery, enabled: !direct && !explicitRecovery });
  const tenants = query.data?.tenants ?? [];
  const term = filter.trim().toLowerCase();
  const matches = tenants.filter((item) =>
    [item.display_name, item.name, item.slug].some((value) => value?.toLowerCase().includes(term))
  );
  const previous = tenants.find((item) => item.slug === (explicit ?? remembered.slug));
  const selectedSlug =
    !showSelector && (tenant === undefined || explicit)
      ? explicitRecovery || previous?.slug
      : undefined;
  const onlyTenant = tenants.length === 1 ? tenants[0] : undefined;
  const resultCount = query.isSuccess && !direct && !selectedSlug ? matches.length : null;
  useAnnounceChange(
    resultCount === null
      ? null
      : t(resultCount === 1 ? "tenant_results_one" : "tenant_results_other", {
          count: resultCount
        }),
    resultCount
  );

  useEffect(() => {
    const candidate =
      explicit ??
      (tenant === undefined && !previous && remembered.available ? onlyTenant?.slug : undefined);
    if (candidate && !suppressAuto && !showSelector && !started.current) {
      started.current = true;
      // Without a remembered choice, a failed login would automatically start
      // again in the next document. Keep the explicit link usable instead.
      const saved = rememberTenant(candidate);
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

  if (selectedSlug) {
    return (
      <>
        <Button
          label={
            failed
              ? t("oidc_retry_login")
              : `${t("continue")} · ${previous?.display_name || previous?.name}`
          }
          href={federationHref(next, selectedSlug)}
          as={DocumentLink}
          onClick={() => rememberTenant(selectedSlug)}
        />
        <Button
          label={t("oidc_choose_another_org")}
          variant="ghost"
          onClick={() => {
            forgetTenant();
            rescueFocus(() => selectorHeading.current);
            setShowSelector(true);
            const params = new URLSearchParams(search.toString());
            for (const key of [
              "tenant",
              "message",
              "error",
              "info",
              "detailCode",
              "correlation",
              "rawDetail"
            ])
              params.delete(key);
            replaceUrl(`/login${params.size ? `?${params}` : ""}`);
          }}
        />
      </>
    );
  }

  return (
    <>
      <p ref={selectorHeading} tabIndex={-1} className="text-ax-text-secondary text-center text-sm">
        {t("select_your_organization")}
      </p>
      <QueryStateBoundary
        query={query}
        rows={2}
        loadingLabel={t("loading_organizations")}
        errorTitle={t("failed_to_load_organizations")}
      >
        {() =>
          tenants.length === 0 ? (
            <p className="text-ax-text-secondary text-center text-sm">
              {t("no_organizations_available")}
            </p>
          ) : (
            <>
              <TextInput
                label={t("search_organizations")}
                placeholder={t("search_by_name_or_municipality")}
                value={filter}
                onChange={setFilter}
                hasClear
                width="100%"
              />
              {matches.length === 0 && (
                <p className="text-ax-text-secondary text-center text-sm">
                  {t("no_organizations_found")}
                </p>
              )}
              <div className="grid max-h-64 gap-2 overflow-y-auto">
                {matches.map((tenant) => (
                  <Button
                    key={tenant.slug}
                    label={tenant.display_name || tenant.name}
                    href={federationHref(next, tenant.slug)}
                    as={DocumentLink}
                    onClick={() => rememberTenant(tenant.slug)}
                  />
                ))}
              </div>
            </>
          )
        }
      </QueryStateBoundary>
    </>
  );
}
