<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { IntegrationKnowledge } from "@intric/intric-js";
  import { IconHistory } from "@intric/icons/history";

  export let knowledge: IntegrationKnowledge;
  export let onShowSyncHistory: (() => void) | undefined = undefined;

  $: syncedAt = knowledge.metadata?.last_synced_at ?? null;

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
</script>

<button
  on:click={onShowSyncHistory}
  disabled={!onShowSyncHistory}
  class="flex min-w-0 flex-col text-xs text-secondary transition-colors hover:text-foreground disabled:cursor-default disabled:hover:text-secondary"
>
  {#if syncedAt}
    <div class="flex items-center gap-1">
      <span class="truncate">
        {m.integration_last_synced()} {getTimeAgo(syncedAt)}
      </span>
      {#if onShowSyncHistory}
        <IconHistory size="sm" class="flex-shrink-0" />
      {/if}
    </div>
  {:else}
    <span class="truncate text-secondary opacity-70">
      {m.integration_sync_summary_none()}
    </span>
  {/if}
</button>
