<script lang="ts">
  import { Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import type { IntricClient } from "@intric/intric-js";
  import dayjs from "dayjs";

  interface SharePointSubscription {
    id: string;
    user_integration_id: string;
    site_id: string;
    subscription_id: string;
    drive_id: string;
    expires_at: string;
    created_at: string;
    is_expired: boolean;
    expires_in_hours: number;
    owner_email: string | null;
    owner_type: "user" | "organization";
  }

  interface SubscriptionRenewalResult {
    total_subscriptions: number;
    expired_count: number;
    recreated: number;
    failed: number;
    errors: string[];
  }

  interface Props {
    intric: IntricClient;
  }

  const { intric }: Props = $props();

  let subscriptions = $state<SharePointSubscription[]>([]);
  let loading = $state(false);
  let renewingAll = $state(false);
  let renewingSubscriptionIds = $state<Set<string>>(new Set());

  // Load subscriptions
  const loadSubscriptions = createAsyncState(async () => {
    loading = true;
    try {
      const response = await intric.integrations.admin.sharepoint.listSubscriptions();
      // Backend returns array directly, not wrapped in object
      subscriptions = Array.isArray(response) ? response : [];
    } catch (error) {
      console.error("Failed to load SharePoint subscriptions:", error);
      alert(m.sharepoint_subscriptions_load_error());
      subscriptions = [];
    } finally {
      loading = false;
    }
  });

  // Load on mount
  $effect(() => {
    loadSubscriptions();
  });

  // Renew all expired subscriptions
  async function renewAllExpired() {
    renewingAll = true;
    try {
      const result: SubscriptionRenewalResult = await intric.integrations.admin.sharepoint.renewExpiredSubscriptions();

      if (result.recreated > 0 && result.failed === 0) {
        alert(
          m.sharepoint_subscriptions_renewed_success({
            count: result.recreated
          })
        );
      } else if (result.failed > 0) {
        alert(
          m.sharepoint_subscriptions_renewed_partial({
            failed: result.failed,
            errors: result.errors.join(", ")
          })
        );
      } else if (result.expired_count === 0) {
        alert(m.sharepoint_subscriptions_none_expired());
      }

      // Reload subscriptions
      await loadSubscriptions();
    } catch (error) {
      console.error("Failed to renew expired subscriptions:", error);
      alert(m.sharepoint_subscriptions_renew_error());
    } finally {
      renewingAll = false;
    }
  }

  // Renew a single subscription
  async function renewSubscription(subscription: SharePointSubscription) {
    renewingSubscriptionIds.add(subscription.id);
    renewingSubscriptionIds = renewingSubscriptionIds; // Trigger reactivity

    try {
      await intric.integrations.admin.sharepoint.recreateSubscription({ id: subscription.id });
      alert(m.sharepoint_subscription_renewed_success());

      // Reload subscriptions
      await loadSubscriptions();
    } catch (error) {
      console.error(`Failed to renew subscription ${subscription.id}:`, error);
      alert(m.sharepoint_subscription_renew_error());
    } finally {
      renewingSubscriptionIds.delete(subscription.id);
      renewingSubscriptionIds = renewingSubscriptionIds; // Trigger reactivity
    }
  }

  // Get status badge class
  function getStatusBadgeClass(subscription: SharePointSubscription): string {
    if (subscription.is_expired) {
      return "bg-negative-dimmer text-negative-stronger";
    } else if (subscription.expires_in_hours <= 48) {
      return "bg-warning-dimmer text-warning-stronger";
    } else {
      return "bg-positive-dimmer text-positive-stronger";
    }
  }

  // Get status label
  function getStatusLabel(subscription: SharePointSubscription): string {
    if (subscription.is_expired) {
      return m.sharepoint_webhook_expired();
    } else if (subscription.expires_in_hours <= 48) {
      return m.sharepoint_webhook_expiring_soon();
    } else {
      return m.sharepoint_webhook_active();
    }
  }

  // Format date
  function formatDate(dateString: string): string {
    const d = dayjs(dateString);
    return d.isValid() ? d.format("YYYY-MM-DD HH:mm") : dateString;
  }

  // Format time duration
  function formatTimeDuration(hours: number): string {
    if (hours < 24) {
      return `${hours}h`;
    }

    const days = Math.floor(hours / 24);
    const remainingHours = hours % 24;

    if (remainingHours === 0) {
      return `${days}d`;
    }

    return `${days}d ${remainingHours}h`;
  }

  // Count expired subscriptions
  let expiredCount = $derived(subscriptions.filter(s => s.is_expired).length);
</script>

<div class="space-y-4">
  <!-- Header with bulk action -->
  <div class="flex items-center justify-between">
    <h3 class="text-lg font-medium">
      {m.sharepoint_subscriptions_title()}
    </h3>

    {#if expiredCount > 0}
      <Button
        variant="primary"
        onclick={renewAllExpired}
        disabled={renewingAll || loading}
      >
        {renewingAll ? m.sharepoint_subscriptions_renewing() : m.sharepoint_subscriptions_renew_all_expired({ count: expiredCount })}
      </Button>
    {/if}
  </div>

  <!-- Description -->
  <p class="text-sm text-secondary">
    {m.sharepoint_subscriptions_description()}
  </p>

  <!-- Loading state -->
  {#if loading && subscriptions.length === 0}
    <div class="rounded-lg border border-border bg-background p-8 text-center">
      <p class="text-sm text-secondary">{m.loading()}</p>
    </div>
  {:else if subscriptions.length === 0}
    <!-- Empty state -->
    <div class="rounded-lg border border-border bg-background p-8 text-center">
      <p class="text-sm text-secondary">
        {m.sharepoint_subscriptions_empty()}
      </p>
    </div>
  {:else}
    <!-- Subscriptions table -->
    <div class="overflow-x-auto rounded-lg border border-border">
      <table class="w-full divide-y divide-border">
        <thead class="bg-muted">
          <tr>
            <th scope="col" class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-foreground">
              {m.sharepoint_subscription_status()}
            </th>
            <th scope="col" class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-foreground">
              {m.sharepoint_subscription_owner()}
            </th>
            <th scope="col" class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-foreground">
              {m.sharepoint_subscription_site()}
            </th>
            <th scope="col" class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-foreground">
              {m.sharepoint_subscription_expires()}
            </th>
            <th scope="col" class="px-3 py-2 text-left text-xs font-medium uppercase tracking-wider text-foreground">
              {m.sharepoint_subscription_created()}
            </th>
            <th scope="col" class="sticky right-0 bg-muted px-3 py-2">
              <span class="sr-only">{m.actions()}</span>
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-border bg-background">
          {#each subscriptions as subscription (subscription.id)}
            <tr class="hover:bg-muted/50 transition-colors">
              <td class="whitespace-nowrap px-3 py-3">
                <div class="flex items-center gap-1">
                  <span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {getStatusBadgeClass(subscription)}">
                    {getStatusLabel(subscription)}
                  </span>
                  <span class="text-xs text-secondary">
                    ({formatTimeDuration(subscription.expires_in_hours)})
                  </span>
                </div>
              </td>
              <td class="whitespace-nowrap px-3 py-3">
                {#if subscription.owner_type === "organization"}
                  <span class="inline-flex items-center rounded-full bg-accent-dimmer px-2 py-0.5 text-xs font-medium text-accent-stronger">
                    {m.sharepoint_subscription_owner_organization()}
                  </span>
                {:else}
                  <span class="max-w-[150px] truncate text-sm text-foreground block" title={subscription.owner_email || ""}>
                    {subscription.owner_email || m.sharepoint_subscription_owner_unknown()}
                  </span>
                {/if}
              </td>
              <td class="px-3 py-3">
                <div class="max-w-[200px] truncate text-sm text-foreground" title={subscription.site_id}>
                  {subscription.site_id}
                </div>
                <div class="max-w-[200px] truncate text-xs text-secondary" title={subscription.drive_id}>
                  {m.sharepoint_drive_label()}: {subscription.drive_id}
                </div>
              </td>
              <td class="whitespace-nowrap px-3 py-3 text-xs text-secondary">
                {formatDate(subscription.expires_at)}
              </td>
              <td class="whitespace-nowrap px-3 py-3 text-xs text-secondary">
                {formatDate(subscription.created_at)}
              </td>
              <td class="sticky right-0 bg-background whitespace-nowrap px-3 py-3 text-right">
                <Button
                  variant="secondary"
                  size="sm"
                  onclick={() => renewSubscription(subscription)}
                  disabled={renewingSubscriptionIds.has(subscription.id) || renewingAll}
                >
                  {renewingSubscriptionIds.has(subscription.id) ? m.sharepoint_subscription_renewing() : m.sharepoint_subscription_renew()}
                </Button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <!-- Summary -->
    <div class="text-sm text-secondary">
      {m.sharepoint_subscriptions_summary({
        total: subscriptions.length,
        expired: expiredCount,
        active: subscriptions.length - expiredCount
      })}
    </div>
  {/if}
</div>
