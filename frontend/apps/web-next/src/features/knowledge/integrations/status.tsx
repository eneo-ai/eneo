"use client";

import type { StatusTone } from "@/components/composites/status-label";
import { History } from "lucide-react";
import { useTranslations } from "next-intl";
import { hoursUntil } from "@/lib/format";
import { ClientTime } from "@/features/spaces/client-time";
import type { IntegrationKnowledge } from "../knowledge";
import { KnowledgeLabel } from "../table-controls-ui";

/** `detailKey` explains the state; an active subscription needs no explanation. */
type WebhookStatus = { tone: StatusTone; labelKey: string; detailKey?: string };

/** A SharePoint item's change subscription: none, active, expiring within 48 h or expired. */
function webhookStatus(item: IntegrationKnowledge): WebhookStatus {
  const expiresAt = item.metadata.sharepoint_subscription_expires_at ?? null;
  if (!expiresAt) {
    return {
      tone: "neutral",
      labelKey: "sharepoint_webhook_none",
      detailKey: "sharepoint_webhook_none_tooltip"
    };
  }
  const hours = hoursUntil(expiresAt);
  if (hours <= 0) {
    return {
      tone: "error",
      labelKey: "sharepoint_webhook_expired",
      detailKey: "sharepoint_webhook_expired_tooltip"
    };
  }
  return hours <= 48
    ? {
        tone: "warning",
        labelKey: "sharepoint_webhook_expiring_soon",
        detailKey: "sharepoint_webhook_auto_renewal"
      }
    : { tone: "success", labelKey: "sharepoint_webhook_active" };
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
  const syncedAt = item.metadata.last_synced_at ?? null;
  const syncLine = syncedAt ? (
    <>
      {t("integration_last_synced")} <ClientTime value={syncedAt} format="date_time" />
    </>
  ) : (
    t("integration_sync_summary_none")
  );
  const webhook = item.integration_type === "sharepoint" ? webhookStatus(item) : null;

  return (
    <div className="flex min-w-0 flex-col items-start gap-1 text-xs">
      {onShowSyncHistory ? (
        <button
          type="button"
          onClick={onShowSyncHistory}
          className="text-ax-text-secondary hover:text-ax-text rounded-ax-inner focus-visible:outline-ring inline-flex min-h-6 max-w-full items-center gap-1 text-start focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
        >
          {/* The visible text first (WCAG 2.5.3), then what the button opens. */}
          <span>{syncLine}</span>
          <History aria-hidden="true" className="size-3 shrink-0" />
          <span className="sr-only">, {t("sync_history")}</span>
        </button>
      ) : (
        <span className="text-ax-text-secondary max-w-full">{syncLine}</span>
      )}
      {webhook ? (
        <KnowledgeLabel
          tone={webhook.tone}
          label={t(webhook.labelKey)}
          detail={webhook.detailKey ? t(webhook.detailKey) : undefined}
        />
      ) : null}
    </div>
  );
}
