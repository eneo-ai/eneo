<script lang="ts">
  import { SvelteSet } from "svelte/reactivity";
  import { LoaderCircle } from "lucide-svelte";
  import type { Eneo, components } from "@eneo/eneo-js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { formatDateTime } from "$lib/features/integrations/sharepoint/format";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";

  type SharePointSubscription = components["schemas"]["SharePointSubscriptionPublic"];
  type SubscriptionRenewalResult = components["schemas"]["SubscriptionRenewalResult"];

  interface Props {
    eneo: Eneo;
  }

  const { eneo }: Props = $props();

  let subscriptions = $state<SharePointSubscription[]>([]);
  let renewingAll = $state(false);
  const renewingSubscriptionIds = new SvelteSet<string>();

  const loadSubscriptions = createAsyncState(async () => {
    try {
      const response = await eneo.integrations.admin.sharepoint.listSubscriptions();
      subscriptions = Array.isArray(response) ? response : [];
    } catch (error) {
      toastError(error, m.sharepoint_subscriptions_load_error());
      subscriptions = [];
    }
  });

  $effect(() => {
    loadSubscriptions();
  });

  async function renewAllExpired() {
    renewingAll = true;
    try {
      const result: SubscriptionRenewalResult =
        await eneo.integrations.admin.sharepoint.renewExpiredSubscriptions();

      if ((result.recreated ?? 0) > 0 && (result.failed ?? 0) === 0) {
        toast.success(m.sharepoint_subscriptions_renewed_success({ count: result.recreated ?? 0 }));
      } else if ((result.failed ?? 0) > 0) {
        toast.error(
          m.sharepoint_subscriptions_renewed_partial({
            failed: result.failed ?? 0,
            errors: (result.errors ?? []).join(", ")
          })
        );
      } else if (result.expired_count === 0) {
        toast.info(m.sharepoint_subscriptions_none_expired());
      }

      await loadSubscriptions();
    } catch (error) {
      toastError(error, m.sharepoint_subscriptions_renew_error());
    } finally {
      renewingAll = false;
    }
  }

  async function renewSubscription(subscription: SharePointSubscription) {
    renewingSubscriptionIds.add(subscription.id);

    try {
      await eneo.integrations.admin.sharepoint.recreateSubscription({ id: subscription.id });
      toast.success(m.sharepoint_subscription_renewed_success());
      await loadSubscriptions();
    } catch (error) {
      toastError(error, m.sharepoint_subscription_renew_error());
    } finally {
      renewingSubscriptionIds.delete(subscription.id);
    }
  }

  function getStatusBadgeClass(subscription: SharePointSubscription): string {
    if (subscription.is_expired) return "bg-negative-dimmer text-negative-stronger";
    if (subscription.expires_in_hours <= 48) return "bg-caution text-caution";
    return "bg-positive-dimmer text-positive-stronger";
  }

  function getStatusLabel(subscription: SharePointSubscription): string {
    if (subscription.is_expired) return m.sharepoint_webhook_expired();
    if (subscription.expires_in_hours <= 48) return m.sharepoint_webhook_expiring_soon();
    return m.sharepoint_webhook_active();
  }

  function getRenewalFailureCount(subscription: SharePointSubscription): number {
    return subscription.consecutive_renewal_failures ?? 0;
  }

  function hasRenewalFailures(subscription: SharePointSubscription): boolean {
    return getRenewalFailureCount(subscription) > 0;
  }

  function getHealthBadgeClass(subscription: SharePointSubscription): string {
    if (hasRenewalFailures(subscription)) return "bg-negative-dimmer text-negative-stronger";
    if (!subscription.last_webhook_received_at) return "bg-caution text-caution";
    return "bg-positive-dimmer text-positive-stronger";
  }

  function getHealthLabel(subscription: SharePointSubscription): string {
    if (hasRenewalFailures(subscription)) {
      return m.sharepoint_subscription_health_failing({
        count: getRenewalFailureCount(subscription)
      });
    }
    if (!subscription.last_webhook_received_at) return m.sharepoint_subscription_health_waiting();
    return m.sharepoint_subscription_health_ok();
  }

  function getHealthDetail(subscription: SharePointSubscription): string {
    if (hasRenewalFailures(subscription)) {
      return `${m.sharepoint_subscription_last_failure()}: ${formatOptionalDateTime(
        subscription.last_renewal_failed_at
      )}`;
    }
    return `${m.sharepoint_subscription_last_webhook()}: ${formatOptionalDateTime(
      subscription.last_webhook_received_at
    )}`;
  }

  function formatOptionalDateTime(dateString?: string | null): string {
    return dateString ? formatDateTime(dateString) : m.sharepoint_subscription_never();
  }

  function formatTimeDuration(hours: number): string {
    if (hours < 24) return `${hours}h`;
    const days = Math.floor(hours / 24);
    const remainingHours = hours % 24;
    return remainingHours === 0 ? `${days}d` : `${days}d ${remainingHours}h`;
  }

  let expiredCount = $derived(subscriptions.filter((s) => s.is_expired).length);
</script>

<div class="flex flex-col gap-4">
  <div class="flex flex-wrap items-center justify-between gap-3">
    <h3 class="text-lg font-medium">
      {m.sharepoint_subscriptions_title()}
    </h3>

    {#if expiredCount > 0}
      <Button onclick={renewAllExpired} disabled={renewingAll || loadSubscriptions.isLoading}>
        {#if renewingAll}
          <LoaderCircle class="animate-spin" aria-hidden="true" />
        {/if}
        {renewingAll
          ? m.sharepoint_subscriptions_renewing()
          : m.sharepoint_subscriptions_renew_all_expired({ count: expiredCount })}
      </Button>
    {/if}
  </div>

  <p class="text-muted-foreground text-sm">
    {m.sharepoint_subscriptions_description()}
  </p>

  {#if loadSubscriptions.isLoading && subscriptions.length === 0}
    <div
      class="border-border text-muted-foreground flex items-center justify-center gap-2 rounded-lg border p-8 text-sm"
      role="status"
    >
      <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
      {m.loading()}
    </div>
  {:else if subscriptions.length === 0}
    <div class="border-border text-muted-foreground rounded-lg border p-8 text-center text-sm">
      {m.sharepoint_subscriptions_empty()}
    </div>
  {:else}
    <div class="border-border overflow-x-auto rounded-lg border">
      <Table.Root>
        <Table.Header>
          <Table.Row>
            <Table.Head>{m.sharepoint_subscription_status()}</Table.Head>
            <Table.Head>{m.sharepoint_subscription_health()}</Table.Head>
            <Table.Head>{m.sharepoint_subscription_owner()}</Table.Head>
            <Table.Head>{m.sharepoint_subscription_site()}</Table.Head>
            <Table.Head>{m.sharepoint_subscription_expires()}</Table.Head>
            <Table.Head>{m.sharepoint_subscription_created()}</Table.Head>
            <Table.Head class="bg-background sticky right-0">
              <span class="sr-only">{m.actions()}</span>
            </Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each subscriptions as subscription (subscription.id)}
            <Table.Row>
              <Table.Cell class="whitespace-nowrap">
                <div class="flex items-center gap-1.5">
                  <Badge class="border-transparent {getStatusBadgeClass(subscription)}">
                    {getStatusLabel(subscription)}
                  </Badge>
                  <span class="text-muted-foreground text-xs">
                    ({formatTimeDuration(subscription.expires_in_hours)})
                  </span>
                </div>
              </Table.Cell>
              <Table.Cell>
                <div class="flex max-w-[220px] flex-col gap-1">
                  <Badge class="w-fit border-transparent {getHealthBadgeClass(subscription)}">
                    {getHealthLabel(subscription)}
                  </Badge>
                  <span
                    class="text-muted-foreground truncate text-xs"
                    title={getHealthDetail(subscription)}
                  >
                    {getHealthDetail(subscription)}
                  </span>
                  {#if hasRenewalFailures(subscription) && subscription.last_renewal_error}
                    <span
                      class="text-negative-stronger truncate text-xs"
                      title={subscription.last_renewal_error}
                    >
                      {subscription.last_renewal_error}
                    </span>
                  {/if}
                </div>
              </Table.Cell>
              <Table.Cell class="whitespace-nowrap">
                {#if subscription.owner_type === "organization"}
                  <Badge class="bg-accent-dimmer text-accent-stronger border-transparent">
                    {m.sharepoint_subscription_owner_organization()}
                  </Badge>
                {:else}
                  <span
                    class="block max-w-[150px] truncate text-sm"
                    title={subscription.owner_email || ""}
                  >
                    {subscription.owner_email || m.sharepoint_subscription_owner_unknown()}
                  </span>
                {/if}
              </Table.Cell>
              <Table.Cell>
                <div class="max-w-[200px] truncate text-sm" title={subscription.site_id}>
                  {subscription.site_id}
                </div>
                <div
                  class="text-muted-foreground max-w-[200px] truncate text-xs"
                  title={subscription.drive_id}
                >
                  {m.sharepoint_drive_label()}: {subscription.drive_id}
                </div>
              </Table.Cell>
              <Table.Cell class="text-muted-foreground text-xs whitespace-nowrap">
                {formatDateTime(subscription.expires_at)}
              </Table.Cell>
              <Table.Cell class="text-muted-foreground text-xs whitespace-nowrap">
                {formatDateTime(subscription.created_at)}
              </Table.Cell>
              <Table.Cell class="bg-background sticky right-0 text-right whitespace-nowrap">
                <Button
                  variant="outline"
                  size="sm"
                  onclick={() => renewSubscription(subscription)}
                  disabled={renewingSubscriptionIds.has(subscription.id) || renewingAll}
                >
                  {#if renewingSubscriptionIds.has(subscription.id)}
                    <LoaderCircle class="animate-spin" aria-hidden="true" />
                  {/if}
                  {renewingSubscriptionIds.has(subscription.id)
                    ? m.sharepoint_subscription_renewing()
                    : m.sharepoint_subscription_renew()}
                </Button>
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    </div>

    <div class="text-muted-foreground text-sm">
      {m.sharepoint_subscriptions_summary({
        total: subscriptions.length,
        expired: expiredCount,
        active: subscriptions.length - expiredCount
      })}
    </div>
  {/if}
</div>
