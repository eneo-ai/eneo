"use client";

import { History } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { formatRelativeTime, hoursUntil } from "@/lib/format";
import type { IntegrationKnowledge } from "../knowledge";

/**
 * Last-sync line (opens the sync history when a handler is given) plus, for
 * SharePoint, the webhook subscription state.
 */
export function IntegrationStatus({
  item,
  onShowSyncHistory
}: {
  item: IntegrationKnowledge;
  onShowSyncHistory?: () => void;
}) {
  const t = useTranslations();
  const locale = useLocale();
  const syncedAt = item.metadata.last_synced_at ?? null;

  let webhook: { label: string; tooltip: string; className: string } | null = null;
  if (item.integration_type === "sharepoint") {
    const expiresAt = item.metadata.sharepoint_subscription_expires_at ?? null;
    if (!expiresAt) {
      webhook = {
        label: t("sharepoint_webhook_none"),
        tooltip: t("sharepoint_webhook_none_tooltip"),
        className: "text-muted-foreground"
      };
    } else {
      const hours = hoursUntil(expiresAt);
      webhook =
        hours <= 0
          ? {
              label: t("sharepoint_webhook_expired"),
              tooltip: t("sharepoint_webhook_expired_tooltip"),
              className: "text-red-600 dark:text-red-400"
            }
          : hours <= 48
            ? {
                label: t("sharepoint_webhook_expiring_soon"),
                tooltip: t("sharepoint_webhook_auto_renewal"),
                className: "text-amber-600 dark:text-amber-400"
              }
            : {
                label: t("sharepoint_webhook_active"),
                tooltip: t("sharepoint_webhook_auto_renewal"),
                className: "text-green-700 dark:text-green-400"
              };
    }
  }

  const syncLine = syncedAt ? (
    <span className="truncate">
      {t("integration_last_synced")} {formatRelativeTime(syncedAt, locale)}
    </span>
  ) : (
    <span className="truncate opacity-70">{t("integration_sync_summary_none")}</span>
  );

  return (
    <div className="flex min-w-0 flex-col gap-0.5 text-xs">
      {onShowSyncHistory ? (
        <button
          type="button"
          onClick={onShowSyncHistory}
          className="text-muted-foreground hover:text-foreground flex min-w-0 cursor-pointer items-center gap-1 text-left transition-colors"
        >
          {syncLine}
          <History className="size-3 shrink-0" />
        </button>
      ) : (
        <span className="text-muted-foreground flex min-w-0 items-center">{syncLine}</span>
      )}
      {webhook && (
        <span className={`truncate ${webhook.className}`} title={webhook.tooltip}>
          {webhook.label}
        </span>
      )}
    </div>
  );
}
