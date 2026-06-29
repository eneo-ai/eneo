"use client";

import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
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
  sharepointAppQueryOptions,
  tenantIntegrationsQueryOptions
} from "@/features/admin/integrations/integrations";
import { SharePointAppConfigDialog } from "./sharepoint-app-config-dialog";
import { SharePointAppDeleteDialog } from "./sharepoint-app-delete-dialog";
import { SharePointSubscriptions } from "./sharepoint-subscriptions";

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

/** SharePoint Azure-AD app config + webhook-subscription management. */
function SharePointAdminSection() {
  const t = useTranslations();
  const { data: config, isPending } = useQuery(sharepointAppQueryOptions(browserApi));
  const [showConfig, setShowConfig] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [showWebhooks, setShowWebhooks] = useState(false);
  const configured = Boolean(config);

  return (
    <Card className="flex flex-col gap-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col">
          <span className="font-medium">SharePoint</span>
          <span className="text-muted-foreground text-xs">
            {isPending
              ? t("loading_configuration")
              : configured
                ? t("organization_access_enabled")
                : t("configure_azure_ad_app")}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowConfig(true)}>
            {configured ? t("update_configuration") : t("configure_sharepoint_app")}
          </Button>
          {configured && (
            <Button variant="outline" size="sm" onClick={() => setShowWebhooks((value) => !value)}>
              {showWebhooks ? t("hide_webhooks") : t("manage_webhooks")}
            </Button>
          )}
        </div>
      </div>

      {configured && showWebhooks && (
        <div className="border-t pt-4">
          <SharePointSubscriptions />
        </div>
      )}

      <SharePointAppConfigDialog
        open={showConfig}
        onOpenChange={setShowConfig}
        onRequestDelete={() => {
          setShowConfig(false);
          setShowDelete(true);
        }}
      />
      <SharePointAppDeleteDialog open={showDelete} onOpenChange={setShowDelete} />
    </Card>
  );
}

/**
 * Tenant knowledge-provider administration: link/unlink providers at the org
 * level, plus SharePoint Azure-AD app config + webhook subscription health.
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
      <SharePointAdminSection />
    </div>
  );
}
