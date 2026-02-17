<script lang="ts">
  import { onMount } from "svelte";
  import { getExpiringKeysStore } from "./expiringKeysStore";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  const { state, refresh } = getExpiringKeysStore();
  const { displayItems } = state;

  // Refresh on mount (respects 60s TTL) — ensures fresh data when dropdown opens
  onMount(() => {
    refresh();
  });
</script>

{#if $displayItems.length > 0}
  <div class="flex flex-col gap-1 px-2 py-2">
    <span class="pl-3 font-medium">{m.api_keys_expiring_bell_title()}</span>
    <div
      class="border-default bg-primary ring-default min-h-10 items-center justify-between rounded-lg border px-3 py-2 shadow"
    >
      {#each $displayItems as item (item.id)}
        <a
          href={localizeHref("/account/api-keys")}
          class="border-dimmer flex items-center justify-between gap-x-3 border-b px-2 py-1.5 whitespace-nowrap last-of-type:border-b-0
                 hover:bg-hover rounded-md transition-colors"
        >
          <div class="flex items-center gap-2 flex-shrink truncate pr-4">
            <span
              class="inline-block h-2 w-2 flex-shrink-0 rounded-full {item.level === 'expired' ||
              item.level === 'urgent'
                ? 'bg-negative'
                : 'bg-caution'}"
            ></span>
            <span class="truncate" title={item.name}>{item.name}</span>
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
        </a>
      {/each}
    </div>
    <a
      href={localizeHref("/account/api-keys")}
      class="text-accent-default hover:text-accent-stronger mt-1 pl-3 text-xs underline underline-offset-2"
    >
      {m.api_keys_expiring_bell_manage()}
    </a>
  </div>
{/if}
