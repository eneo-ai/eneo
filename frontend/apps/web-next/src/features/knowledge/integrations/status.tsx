"use client";

import type { StatusTone } from "@/components/composites/status-label";
import { History } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { formatRelativeTime, hoursUntil } from "@/lib/format";
import type { IntegrationKnowledge } from "../knowledge";
import { KnowledgeLabel } from "../websites";

type WebhookStatus = { tone: StatusTone; labelKey: string; tooltipKey: string };

/** A SharePoint item's change subscription: none, active, expiring within 48 h or expired. */
function webhookStatus(item: IntegrationKnowledge): WebhookStatus {
  const expiresAt = item.metadata.sharepoint_subscription_expires_at ?? null;
  if (!expiresAt) {
    return {
      tone: "neutral",
      labelKey: "sharepoint_webhook_none",
      tooltipKey: "sharepoint_webhook_none_tooltip"
    };
  }
  const hours = hoursUntil(expiresAt);
  if (hours <= 0) {
    return {
      tone: "error",
      labelKey: "sharepoint_webhook_expired",
      tooltipKey: "sharepoint_webhook_expired_tooltip"
    };
  }
  return hours <= 48
    ? {
        tone: "warning",
        labelKey: "sharepoint_webhook_expiring_soon",
        tooltipKey: "sharepoint_webhook_auto_renewal"
      }
    : {
        tone: "success",
        labelKey: "sharepoint_webhook_active",
        tooltipKey: "sharepoint_webhook_auto_renewal"
      };
}

/**
 * Last-sync line (a button to the sync history when a handler is given) plus,
 * for SharePoint, the webhook subscription as a status dot and text.
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
  const syncLine = syncedAt
    ? `${t("integration_last_synced")} ${formatRelativeTime(syncedAt, locale)}`
    : t("integration_sync_summary_none");
  const webhook = item.integration_type === "sharepoint" ? webhookStatus(item) : null;

  return (
    <div className="flex min-w-0 flex-col items-start gap-1 text-xs">
      {onShowSyncHistory ? (
        <button
          type="button"
          onClick={onShowSyncHistory}
          // The visible text first (WCAG 2.5.3), then what the button opens.
          aria-label={`${syncLine}, ${t("sync_history")}`}
          className="text-ax-text-secondary hover:text-ax-text rounded-ax-inner focus-visible:outline-ring inline-flex min-h-6 max-w-full items-center gap-1 text-start focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
        >
          <span className="truncate">{syncLine}</span>
          <History aria-hidden="true" className="size-3 shrink-0" />
        </button>
      ) : (
        <span className="text-ax-text-secondary max-w-full truncate">{syncLine}</span>
      )}
      {webhook ? (
        <KnowledgeLabel
          tone={webhook.tone}
          label={t(webhook.labelKey)}
          tooltip={t(webhook.tooltipKey)}
        />
      ) : null}
    </div>
  );
}
