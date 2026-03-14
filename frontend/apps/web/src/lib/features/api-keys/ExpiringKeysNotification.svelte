<script lang="ts">
  import { onMount } from "svelte";
  import { getExpiringKeysStore } from "./expiringKeysStore";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  const { state, refresh } = getExpiringKeysStore();
  const { displayItems, summary, hasUrgent } = state;

  const MAX_VISIBLE = 5;

  // Refresh on mount (respects 60s TTL) — ensures fresh data when dropdown opens
  onMount(() => {
    refresh();
  });

  // Detect duplicate names to show key suffix for disambiguation
  function hasDuplicateName(name: string, items: typeof $displayItems): boolean {
    return items.filter((i) => i.name === name).length > 1;
  }
</script>

{#if $displayItems.length > 0}
  {@const counts = $summary?.counts_by_severity}
  {@const expiredCount = counts?.expired ?? 0}
  {@const urgentCount = counts?.urgent ?? 0}
  {@const warningCount = counts?.warning ?? 0}
  {@const visibleItems = $displayItems.slice(0, MAX_VISIBLE)}
  {@const overflowCount = $displayItems.length - MAX_VISIBLE}
  <div class="flex flex-col gap-1 px-2 py-2" role="status">
    <span class="pl-3 font-medium">{m.api_keys_expiring_bell_title()}</span>

    {#if expiredCount > 0 || urgentCount > 0 || warningCount > 0}
      <span class="pl-3 text-xs text-secondary">
        {#if expiredCount > 0}
          <span class="text-negative">{m.api_keys_expiring_bell_summary_expired({ count: expiredCount })}</span>
        {/if}
        {#if urgentCount > 0}
          {#if expiredCount > 0}<span>, </span>{/if}
          <span class="text-negative">{m.api_keys_expiring_bell_summary_urgent({ count: urgentCount })}</span>
        {/if}
        {#if warningCount > 0}
          {#if expiredCount > 0 || urgentCount > 0}<span>, </span>{/if}
          <span class="text-caution">{m.api_keys_expiring_bell_summary_warning({ count: warningCount })}</span>
        {/if}
      </span>
    {/if}

    <div
      class="border-default ring-default min-h-10 items-center justify-between rounded-lg border px-3 py-2 shadow
             {$hasUrgent ? 'bg-negative/5' : warningCount > 0 ? 'bg-caution/5' : 'bg-primary'}"
    >
      {#each visibleItems as item (item.id)}
        <div
          class="border-dimmer flex items-center justify-between gap-x-3 border-b px-2 py-1.5 whitespace-nowrap last-of-type:border-b-0"
        >
          <div class="flex items-center gap-2 flex-shrink truncate pr-4">
            <span
              aria-hidden="true"
              class="inline-block flex-shrink-0 rounded-full {item.level === 'expired' || item.level === 'urgent'
                ? 'bg-negative h-2.5 w-2.5'
                : 'bg-caution h-2 w-2'}"
            ></span>
            <span
              class="truncate {item.level === 'expired' ? 'font-medium' : ''}"
              title={item.name}
            >
              {item.name}
            </span>
            {#if item.keySuffix && hasDuplicateName(item.name, $displayItems)}
              <span class="text-tertiary text-xs font-mono flex-shrink-0"
                >&middot; ...{item.keySuffix}</span
              >
            {/if}
          </div>
          <div class="flex-shrink-0 text-right">
            {#if item.level === "expired"}
              <span class="text-negative font-medium text-xs"
                >{m.api_keys_expiring_item_expired()}</span
              >
            {:else if item.daysRemaining === 0}
              <span class="text-negative text-xs">{m.api_keys_expiring_item_today()}</span>
            {:else if item.daysRemaining === 1}
              <span class="text-negative text-xs">{m.api_keys_expiring_item_tomorrow()}</span>
            {:else}
              <span
                class="{item.level === 'urgent' ? 'text-negative' : 'text-caution'} text-xs"
              >
                {m.api_keys_expiring_item_days({ days: item.daysRemaining })}
              </span>
            {/if}
          </div>
        </div>
      {/each}

      {#if overflowCount > 0}
        <div class="px-2 py-1.5 text-xs text-secondary">
          {m.api_keys_expiring_bell_more({ count: overflowCount })}
        </div>
      {/if}
    </div>

    <a
      href={localizeHref("/account/api-keys")}
      class="flex items-center justify-between gap-2 rounded-md px-3 py-2 min-h-[44px]
             text-sm font-medium text-accent-default hover:bg-hover
             focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-default/50
             transition-colors"
    >
      {m.api_keys_expiring_bell_manage()}
      <IconChevronRight class="h-4 w-4" />
    </a>
  </div>
{/if}
