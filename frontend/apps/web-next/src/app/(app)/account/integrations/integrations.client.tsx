"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { EmptyState } from "@/components/composites/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";

function IntegrationCard({ integration }: { integration: Schema<"UserIntegration"> }) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const disconnect = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/integrations/users/{user_integration_id}/", {
          params: { path: { user_integration_id: integration.id ?? "" } }
        })
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integrations", "me"] }),
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Card>
      <CardContent className="flex items-center justify-between gap-4">
        <div className="flex flex-col gap-1">
          <span className="flex items-center gap-2 font-medium">
            {integration.name}
            <Badge variant={integration.connected ? "default" : "outline"}>
              {integration.connected ? t("connected") : t("connect")}
            </Badge>
          </span>
          <p className="text-muted-foreground text-sm">{integration.description}</p>
        </div>
        {/* The OAuth connect popup flow lands in Phase 6 with the rest of integrations. */}
        {integration.connected && (
          <Button
            variant="outline"
            disabled={disconnect.isPending}
            onClick={() => disconnect.mutate()}
          >
            {t("disconnect")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export function AccountIntegrations() {
  const t = useTranslations();

  const { data: integrations, isPending } = useQuery({
    queryKey: ["integrations", "me"],
    queryFn: async () => {
      const result = await unwrap(browserApi.GET("/api/v1/integrations/me/"));
      return result.items;
    }
  });

  if (!isPending && (integrations ?? []).length === 0) {
    return <EmptyState title={t("integrations")} description={t("no_results")} />;
  }

  return (
    <div className="flex flex-col gap-3">
      {(integrations ?? []).map((integration) => (
        <IntegrationCard key={integration.id ?? integration.name} integration={integration} />
      ))}
    </div>
  );
}
