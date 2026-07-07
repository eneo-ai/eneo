"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { formatDateTime } from "@/lib/format";
import {
  SHAREPOINT_SUBSCRIPTIONS_KEY,
  type SharePointSubscription,
  sharepointSubscriptionsQueryOptions
} from "./integrations";

export function SharePointSubscriptions() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: SHAREPOINT_SUBSCRIPTIONS_KEY });

  const { data: subscriptions, isPending } = useQuery(
    sharepointSubscriptionsQueryOptions(browserApi)
  );
  const [renewingId, setRenewingId] = useState<string | null>(null);

  const renewAll = useMutation({
    mutationFn: () =>
      unwrap(browserApi.POST("/api/v1/admin/sharepoint/subscriptions/renew-expired")),
    onSuccess: (result) => {
      if (result.failed && result.failed > 0) {
        toast.warning(
          t("sharepoint_subscriptions_renewed_partial", {
            failed: result.failed,
            errors: (result.errors ?? []).join(", ")
          })
        );
      } else {
        toast.success(
          t("sharepoint_subscriptions_renewed_success", { count: result.recreated ?? 0 })
        );
      }
      void invalidate();
    },
    onError: (error) => toastApiError(error, t)
  });

  const recreate = useMutation({
    mutationFn: (id: string) => {
      setRenewingId(id);
      return unwrap(
        browserApi.POST("/api/v1/admin/sharepoint/subscriptions/{subscription_id}/recreate", {
          params: { path: { subscription_id: id } }
        })
      );
    },
    onSuccess: () => {
      toast.success(t("sharepoint_subscription_renewed_success"));
      void invalidate();
    },
    onError: (error) => toastApiError(error, t),
    onSettled: () => setRenewingId(null)
  });

  const items = subscriptions ?? [];
  const expiredCount = items.filter((sub) => sub.is_expired).length;
  const activeCount = items.length - expiredCount;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-col">
          <span className="text-sm font-medium">{t("sharepoint_subscriptions_title")}</span>
          {items.length > 0 && (
            <span className="text-muted-foreground text-xs">
              {t("sharepoint_subscriptions_summary", {
                total: items.length,
                active: activeCount,
                expired: expiredCount
              })}
            </span>
          )}
        </div>
        {expiredCount > 0 && (
          <Button
            variant="outline"
            size="sm"
            disabled={renewAll.isPending}
            onClick={() => renewAll.mutate()}
          >
            <RefreshCw className={renewAll.isPending ? "size-4 animate-spin" : "size-4"} />
            {t("sharepoint_subscriptions_renew_all_expired", { count: expiredCount })}
          </Button>
        )}
      </div>

      {isPending ? (
        <Skeleton className="h-32 w-full" />
      ) : items.length === 0 ? (
        <p className="text-muted-foreground py-4 text-center text-sm">
          {t("sharepoint_subscriptions_empty")}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("sharepoint_subscription_status")}</TableHead>
                <TableHead>{t("sharepoint_subscription_health")}</TableHead>
                <TableHead>{t("sharepoint_subscription_owner")}</TableHead>
                <TableHead>{t("sharepoint_subscription_site")}</TableHead>
                <TableHead>{t("sharepoint_subscription_expires")}</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((sub) => (
                <TableRow key={sub.id}>
                  <TableCell>
                    <StatusBadge sub={sub} t={t} />
                  </TableCell>
                  <TableCell>
                    <HealthBadge sub={sub} t={t} />
                  </TableCell>
                  <TableCell className="text-sm">
                    {sub.owner_type === "organization"
                      ? t("sharepoint_subscription_owner_organization")
                      : (sub.owner_email ?? t("sharepoint_subscription_owner_unknown"))}
                  </TableCell>
                  <TableCell className="text-muted-foreground font-mono text-xs">
                    {sub.site_id?.slice(0, 12)}…
                  </TableCell>
                  <TableCell className="text-muted-foreground text-sm whitespace-nowrap">
                    {formatDateTime(sub.expires_at)}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={recreate.isPending && renewingId === sub.id}
                      onClick={() => recreate.mutate(sub.id)}
                    >
                      {recreate.isPending && renewingId === sub.id
                        ? t("sharepoint_subscription_renewing")
                        : t("sharepoint_subscription_renew")}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function StatusBadge({
  sub,
  t
}: {
  sub: SharePointSubscription;
  t: ReturnType<typeof useTranslations>;
}) {
  if (sub.is_expired) return <Badge variant="destructive">{t("sharepoint_webhook_expired")}</Badge>;
  if (sub.expires_in_hours <= 48)
    return (
      <Badge variant="outline" className="border-warning/30 text-warning">
        {t("sharepoint_webhook_expiring_soon")}
      </Badge>
    );
  return (
    <Badge variant="outline" className="border-success/30 text-success">
      {t("sharepoint_webhook_active")}
    </Badge>
  );
}

function HealthBadge({
  sub,
  t
}: {
  sub: SharePointSubscription;
  t: ReturnType<typeof useTranslations>;
}) {
  if (sub.consecutive_renewal_failures > 0) {
    return (
      <div className="flex flex-col gap-0.5">
        <Badge variant="destructive">
          {t("sharepoint_subscription_health_failing", {
            count: sub.consecutive_renewal_failures
          })}
        </Badge>
        {sub.last_renewal_error && (
          <span
            className="text-muted-foreground max-w-48 truncate text-xs"
            title={sub.last_renewal_error}
          >
            {sub.last_renewal_error}
          </span>
        )}
      </div>
    );
  }
  if (!sub.last_webhook_received_at) {
    return (
      <Badge variant="outline" className="border-warning/30 text-warning">
        {t("sharepoint_subscription_health_waiting")}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="border-success/30 text-success">
      {t("sharepoint_subscription_health_ok")}
    </Badge>
  );
}
