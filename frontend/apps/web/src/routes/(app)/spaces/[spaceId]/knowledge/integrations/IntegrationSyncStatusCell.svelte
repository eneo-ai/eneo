<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconHistory } from "@eneo/icons/history";
  import { Info } from "@lucide/svelte";
  import { Badge, type BadgeVariant } from "$lib/components/ui/badge/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import {
    aggregateIntegrationSync,
    summarizeIntegrationSync,
    type IntegrationSyncState
  } from "$lib/features/integrations/syncStatus";

  interface Props {
    /** One item, or every item of a wrapper for an aggregated row. */
    knowledge: IntegrationKnowledge | IntegrationKnowledge[];
    onShowSyncHistory?: (() => void) | undefined;
    /** The item's documents page; the document count links there. */
    documentsHref?: string | undefined;
  }

  let { knowledge, onShowSyncHistory, documentsHref }: Props = $props();

  let single = $derived(Array.isArray(knowledge) ? null : knowledge);
  let summary = $derived(
    Array.isArray(knowledge)
      ? aggregateIntegrationSync(knowledge)
      : summarizeIntegrationSync(knowledge)
  );
  let errorMessages = $derived(summary.errors.filter((error) => error.message.length > 0));
  let errorOpen = $state(false);

  let subscriptionExpiresAt = $derived(
    single?.metadata?.sharepoint_subscription_expires_at ?? null
  );
  let isSharePoint = $derived(single?.integration_type === "sharepoint");

  type SubscriptionStatus = "none" | "expired" | "expiring_soon" | "active";

  let subscriptionStatus = $derived.by((): SubscriptionStatus | null => {
    if (!isSharePoint) return null;
    if (!subscriptionExpiresAt) return "none";

    const hoursUntilExpiry =
      (new Date(subscriptionExpiresAt).getTime() - Date.now()) / (1000 * 60 * 60);

    if (hoursUntilExpiry <= 0) return "expired";
    if (hoursUntilExpiry <= 48) return "expiring_soon";
    return "active";
  });

  function getTimeAgo(value: string): string {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    const seconds = Math.floor((Date.now() - date.getTime()) / 1000);

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
  }

  function getStateLabel(state: IntegrationSyncState): string {
    switch (state) {
      case "never":
        return m.integration_sync_status_never();
      case "success":
        return m.integration_sync_status_success();
      case "error":
        return m.integration_sync_status_error();
      case "empty":
        return m.integration_sync_status_empty();
    }
  }

  function getStateBadge(state: IntegrationSyncState): { variant: BadgeVariant; class: string } {
    switch (state) {
      case "never":
        return { variant: "outline", class: "" };
      case "success":
        return { variant: "secondary", class: "bg-positive-dimmer text-positive-stronger" };
      case "error":
        return { variant: "secondary", class: "bg-negative-dimmer text-negative-stronger" };
      case "empty":
        return { variant: "secondary", class: "bg-warning-dimmer text-warning-stronger" };
    }
  }

  function getSubscriptionStatusLabel(status: SubscriptionStatus): string {
    switch (status) {
      case "none":
        return m.sharepoint_webhook_none();
      case "expired":
        return m.sharepoint_webhook_expired();
      case "expiring_soon":
        return m.sharepoint_webhook_expiring_soon();
      case "active":
        return m.sharepoint_webhook_active();
    }
  }

  function getSubscriptionExplanation(status: SubscriptionStatus): string {
    switch (status) {
      case "none":
        return m.sharepoint_webhook_none_tooltip();
      case "expired":
        return m.sharepoint_webhook_expired_tooltip();
      case "expiring_soon":
      case "active":
        return m.sharepoint_webhook_auto_renewal();
    }
  }

  function getSubscriptionStatusClass(status: SubscriptionStatus): string {
    switch (status) {
      case "none":
        return "text-muted";
      case "expired":
        return "text-negative-stronger";
      case "expiring_soon":
        return "text-warning-stronger";
      case "active":
        return "text-positive-stronger";
    }
  }

  let stateBadge = $derived(getStateBadge(summary.state));
  let documentsLabel = $derived(
    summary.documentCount === 1
      ? m.integration_documents_one({ count: summary.documentCount })
      : m.integration_documents_other({ count: summary.documentCount })
  );
  let timelineLabel = $derived.by(() => {
    if (summary.lastSyncedAt) {
      return `${m.integration_last_synced()} ${getTimeAgo(summary.lastSyncedAt)}`;
    }
    if (summary.lastSyncAttemptedAt) {
      return `${m.integration_last_sync_attempted()} ${getTimeAgo(summary.lastSyncAttemptedAt)}`;
    }
    return m.integration_sync_summary_none();
  });
</script>

<div class="flex min-w-0 flex-col gap-1 text-xs">
  <div class="flex flex-wrap items-center gap-x-2 gap-y-1">
    <Badge variant={stateBadge.variant} class={stateBadge.class}>
      {getStateLabel(summary.state)}
    </Badge>
    {#if summary.state !== "never"}
      {#if documentsHref}
        <!-- eslint-disable svelte/no-navigation-without-resolve -- link is a typed prop passed from caller -->
        <a
          href={documentsHref}
          class="text-secondary hover:text-foreground focus-visible:ring-stronger rounded underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
        >
          {documentsLabel}
        </a>
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      {:else}
        <span class="text-secondary">{documentsLabel}</span>
      {/if}
    {/if}
  </div>

  {#if onShowSyncHistory}
    <button
      type="button"
      onclick={onShowSyncHistory}
      class="text-secondary hover:text-foreground focus-visible:ring-stronger flex w-fit min-w-0 items-center gap-1 rounded text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
    >
      <span class="truncate">{timelineLabel}</span>
      <IconHistory size="sm" class="flex-shrink-0" />
      <span class="sr-only">{m.sync_history()}</span>
    </button>
  {:else}
    <span class="text-secondary truncate">{timelineLabel}</span>
  {/if}

  {#if summary.state === "error" && errorMessages.length > 0}
    <Collapsible.Root bind:open={errorOpen}>
      <Collapsible.Trigger
        class="text-negative-stronger focus-visible:ring-stronger w-fit rounded font-medium hover:underline focus-visible:ring-2 focus-visible:outline-none"
      >
        {errorOpen ? m.integration_sync_error_hide() : m.integration_sync_error_show()}
      </Collapsible.Trigger>
      <Collapsible.Content>
        <ul class="text-negative-stronger mt-1 space-y-0.5 break-words whitespace-normal">
          {#each errorMessages as error, index (index)}
            <li>
              {#if error.itemName}
                <span class="font-medium">{error.itemName}:</span>
              {/if}
              {error.message}
            </li>
          {/each}
        </ul>
      </Collapsible.Content>
    </Collapsible.Root>
  {/if}

  {#if subscriptionStatus}
    <Tooltip.Root>
      <Tooltip.Trigger>
        <!-- The explanation is part of the name, so the open tooltip must not
             also describe the trigger with the same text. -->
        {#snippet child({ props })}
          <button
            {...props}
            aria-describedby={undefined}
            class="focus-visible:ring-stronger flex w-fit cursor-default items-center gap-1 rounded text-left focus-visible:ring-2 focus-visible:outline-none {getSubscriptionStatusClass(
              subscriptionStatus
            )}"
          >
            <span class="truncate">{getSubscriptionStatusLabel(subscriptionStatus)}</span>
            <Info class="size-3.5 shrink-0" aria-hidden="true" />
            <span class="sr-only">{getSubscriptionExplanation(subscriptionStatus)}</span>
          </button>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content>{getSubscriptionExplanation(subscriptionStatus)}</Tooltip.Content>
    </Tooltip.Root>
  {/if}
</div>
