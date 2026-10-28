<script lang="ts">
  import SourceStateBadge from "$lib/features/integrations/components/SourceStateBadge.svelte";
  import SyncProgressBar from "$lib/features/integrations/components/SyncProgressBar.svelte";
  import type { SourceSummary } from "$lib/features/integrations/sources";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    summary: SourceSummary;
    sourceName: string;
  }

  let { summary, sourceName }: Props = $props();
</script>

<!-- The problems themselves are on the source's page; the list only says that there are some. -->
{#if summary.progress}
  {@const progress = summary.progress}
  <div class="flex w-40 max-w-full flex-col gap-1.5 text-xs">
    <span class="text-accent-stronger font-medium">
      {progress.total === null
        ? m.integration_progress_syncing_so_far({ count: progress.done })
        : m.integration_progress_syncing_of_total({ done: progress.done, total: progress.total })}
    </span>
    <SyncProgressBar {progress} label={m.integration_progress_label({ name: sourceName })} />
    {#if progress.skipped > 0}
      <span class="text-warning-stronger">
        {m.integration_progress_skipped({ count: progress.skipped })}
      </span>
    {/if}
    {#if summary.failedItems.length > 0}
      <SourceStateBadge state="attention" class="w-fit" />
    {/if}
  </div>
{:else}
  <div class="flex flex-col items-start gap-1">
    <SourceStateBadge state={summary.state} />
    {#if summary.state === "queued" && summary.failedItems.length > 0}
      <SourceStateBadge state="attention" />
    {/if}
    <!-- A source where only some folders wait reads as up to date by its badge alone. -->
    {#if summary.waitingItems > 0 && summary.state !== "never"}
      <span class="text-secondary text-xs">
        {summary.waitingItems === 1
          ? m.integration_source_waiting_one()
          : m.integration_source_waiting_other({ count: summary.waitingItems })}
      </span>
    {/if}
  </div>
{/if}
