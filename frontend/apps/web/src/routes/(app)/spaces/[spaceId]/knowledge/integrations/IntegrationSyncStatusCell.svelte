<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { IntegrationKnowledge } from "@intric/intric-js";
  import { IconHistory } from "@intric/icons/history";

  interface Props {
    knowledge: IntegrationKnowledge;
    onShowSyncHistory?: (() => void) | undefined;
  }

  let { knowledge, onShowSyncHistory }: Props = $props();

  let syncedAt = $derived(knowledge.metadata?.last_synced_at ?? null);
  let subscriptionExpiresAt = $derived(knowledge.metadata?.sharepoint_subscription_expires_at ?? null);
  let isSharePoint = $derived(knowledge.integration_type === "sharepoint");

  // Compute subscription status
  let subscriptionStatus = $derived.by(() => {
    if (!isSharePoint || !subscriptionExpiresAt) return null;

    const now = new Date();
    const expiresAt = new Date(subscriptionExpiresAt);
    const hoursUntilExpiry = (expiresAt.getTime() - now.getTime()) / (1000 * 60 * 60);

    if (hoursUntilExpiry <= 0) return "expired";
    if (hoursUntilExpiry <= 48) return "expiring_soon";
    return "active";
  });

  let subscriptionExpiresInHours = $derived.by(() => {
    if (!subscriptionExpiresAt) return null;
    const now = new Date();
    const expiresAt = new Date(subscriptionExpiresAt);
    const hours = Math.max(0, Math.floor((expiresAt.getTime() - now.getTime()) / (1000 * 60 * 60)));
    return hours;
  });

  function getTimeAgo(value: string): string {
    try {
      const date = new Date(value);
      const now = new Date();
      const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

      if (seconds < 60) return m.integration_last_synced_just_now();
      if (seconds < 3600) {
        const minutes = Math.floor(seconds / 60);
        return m.integration_last_synced_minutes_ago({ minutes });
      }
      if (seconds < 86400) {
        const hours = Math.floor(seconds / 3600);
        return m.integration_last_synced_hours_ago({ hours });
      }
      const days = Math.floor(seconds / 86400);
      return m.integration_last_synced_days_ago({ days });
    } catch (error) {
      return value;
    }
  }

  function getSubscriptionStatusLabel(status: string): string {
    switch (status) {
      case "expired":
        return m.sharepoint_webhook_expired();
      case "expiring_soon":
        return m.sharepoint_webhook_expiring_soon();
      case "active":
        return m.sharepoint_webhook_active();
      default:
        return "";
    }
  }

  function getSubscriptionStatusColor(status: string): string {
    switch (status) {
      case "expired":
        return "text-red-600";
      case "expiring_soon":
        return "text-yellow-600";
      case "active":
        return "text-green-600";
      default:
        return "";
    }
  }
</script>

<div class="flex min-w-0 flex-col gap-1">
  <!-- Sync status button -->
  <button
    onclick={onShowSyncHistory}
    disabled={!onShowSyncHistory}
    class="flex min-w-0 items-center gap-1 text-xs text-secondary transition-colors hover:text-foreground disabled:cursor-default disabled:hover:text-secondary"
  >
    {#if syncedAt}
      <span class="truncate">
        {m.integration_last_synced()} {getTimeAgo(syncedAt)}
      </span>
      {#if onShowSyncHistory}
        <IconHistory size="sm" class="flex-shrink-0" />
      {/if}
    {:else}
      <span class="truncate text-secondary opacity-70">
        {m.integration_sync_summary_none()}
      </span>
    {/if}
  </button>

  <!-- SharePoint subscription status -->
  {#if isSharePoint && subscriptionStatus}
    <div
      class="flex items-center gap-1 text-xs {getSubscriptionStatusColor(subscriptionStatus)}"
      title={subscriptionStatus === "expired"
        ? m.sharepoint_webhook_expired_tooltip()
        : m.sharepoint_webhook_auto_renewal()}
    >
      <span class="truncate">
        {getSubscriptionStatusLabel(subscriptionStatus)}
      </span>
      {#if subscriptionExpiresInHours !== null}
        <span class="text-secondary">
          ({subscriptionExpiresInHours}h)
        </span>
      {/if}
    </div>
  {/if}
</div>
