"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { useRef } from "react";
import { useTranslations } from "use-intl";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { EmptyState } from "@/components/composites/empty-state";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { useFocusRescue } from "@/lib/focus-rescue";
import Link from "@/lib/link";
import { useIntegrationAuth } from "@/features/integrations/use-integration-auth";
import { VendorIcon } from "@/features/knowledge/integrations/vendor";

type UserIntegration = Schema<"UserIntegration">;

function IntegrationCard({
  integration,
  onConnect,
  onDisconnected,
  connecting
}: {
  integration: UserIntegration;
  onConnect: () => void;
  onDisconnected: () => Promise<void>;
  connecting: boolean;
}) {
  const t = useTranslations();
  const tenantAppMissing = integration.tenant_app_configured === false;
  const connectionId = integration.id;

  const disconnect = useMutation({
    mutationFn: (id: string) =>
      unwrap(
        browserApi.DELETE("/api/v1/integrations/users/{user_integration_id}/", {
          params: { path: { user_integration_id: id } }
        })
      ),
    onSuccess: onDisconnected,
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Card className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2 font-medium">
          <VendorIcon type={integration.integration_type} />
          {integration.name}
          {integration.auth_type === "tenant_app" && <Badge label={t("integration_org_badge")} />}
          {integration.auth_type === "user_oauth" && (
            <Badge label={t("integration_personal_badge")} />
          )}
          {integration.connected && !tenantAppMissing && <Badge label={t("connected")} />}
        </div>
        <p className="text-muted-foreground text-sm">{integration.description}</p>
        {tenantAppMissing && (
          <p className="text-warning text-sm">{t("contact_admin_to_configure")}</p>
        )}
      </div>
      {tenantAppMissing ? (
        <Button label={t("not_available")} isDisabled />
      ) : integration.connected && connectionId ? (
        <ConfirmDialog
          trigger={<Button label={t("disconnect")} />}
          title={t("disconnect_name", { name: integration.name })}
          description={t("do_you_really_want_to_disconnect_name", { name: integration.name })}
          confirmLabel={t("disconnect")}
          pending={disconnect.isPending}
          onConfirm={() => disconnect.mutateAsync(connectionId)}
        />
      ) : (
        <Button
          label={t("connect")}
          isLoading={connecting}
          isInterruptible
          onClick={() => {
            if (!connecting) onConnect();
          }}
        />
      )}
    </Card>
  );
}

export function AccountIntegrations() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { can } = useAppContext();
  const panel = useRef<HTMLElement>(null);
  const rescueFocus = useFocusRescue();

  const integrations = useQuery({
    queryKey: ["integrations", "me"],
    queryFn: async () => {
      const result = await unwrap(browserApi.GET("/api/v1/integrations/me/"));
      return result.items;
    },
    select: (items) => items.filter((integration) => integration.integration_type === "sharepoint")
  });

  const { connect, isConnecting } = useIntegrationAuth((result) => {
    if (result.success) {
      toast.success(`${result.integration.name}: ${t("connected")}`);
      void queryClient.invalidateQueries({ queryKey: ["integrations"] });
    } else {
      toastApiError(result.error, t);
    }
  });

  return (
    <section ref={panel} tabIndex={-1} aria-label={t("integrations")}>
      <QueryStateBoundary query={integrations}>
        {(items) =>
          items.length === 0 ? (
            <EmptyState
              title={t("integrations")}
              description={t("no_integrations_enabled")}
              actions={
                can("admin") ? (
                  <p>
                    {t("enable_integrations_admin")}{" "}
                    <Link href="/admin/integrations?tab=providers" className="underline">
                      {t("integrations_admin_menu")}
                    </Link>
                  </p>
                ) : undefined
              }
            />
          ) : (
            <div className="flex flex-col gap-3">
              {items.map((integration) => (
                <IntegrationCard
                  key={`${integration.tenant_integration_id}-${integration.auth_type ?? "user_oauth"}`}
                  integration={integration}
                  connecting={isConnecting(integration)}
                  onConnect={() => void connect(integration)}
                  onDisconnected={() => {
                    rescueFocus(() => panel.current);
                    return queryClient.invalidateQueries({ queryKey: ["integrations"] });
                  }}
                />
              ))}
            </div>
          )
        }
      </QueryStateBoundary>
    </section>
  );
}
