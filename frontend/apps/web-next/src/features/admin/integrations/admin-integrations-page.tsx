"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import {
  type TenantIntegration,
  TENANT_INTEGRATIONS_KEY,
  tenantIntegrationsQueryOptions
} from "@/features/admin/integrations/integrations";

function IntegrationCard({ integration }: { integration: TenantIntegration }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: TENANT_INTEGRATIONS_KEY });

  const link = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/integrations/tenant/add/{integration_id}/", {
          params: { path: { integration_id: integration.integration_id } }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const unlink = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/integrations/tenant/remove/{tenant_integration_id}/", {
          params: { path: { tenant_integration_id: integration.id as string } }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const linked = integration.is_linked_to_tenant;

  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <span className="font-medium">{integration.name}</span>
        {linked && <Badge>{t("integration_status_configured")}</Badge>}
      </div>
      <p className="text-muted-foreground flex-1 text-sm">{integration.description}</p>
      {linked ? (
        <Button
          variant="outline"
          size="sm"
          disabled={unlink.isPending || !integration.id}
          onClick={() => unlink.mutate()}
        >
          {t("disable")}
        </Button>
      ) : (
        <Button size="sm" disabled={link.isPending} onClick={() => link.mutate()}>
          {t("enable")}
        </Button>
      )}
    </Card>
  );
}

/**
 * Tenant knowledge-provider administration: link/unlink providers at the org
 * level. The SharePoint Azure-AD app credential setup and webhook-subscription
 * management (untyped admin endpoints) are deferred — see the ledger.
 */
export function AdminIntegrationsPage() {
  const t = useTranslations();
  const { data: integrations } = useSuspenseQuery(tenantIntegrationsQueryOptions(browserApi));

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("integrations")} />
      <p className="text-muted-foreground text-sm">{t("admin_integrations_grid_hint")}</p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {integrations.map((integration) => (
          <IntegrationCard key={integration.integration_id} integration={integration} />
        ))}
      </div>
      <p className="text-muted-foreground border-border rounded-lg border border-dashed p-4 text-xs">
        {t("admin_integrations_advanced_deferred")}
      </p>
    </div>
  );
}
