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
    {#if summary.failedItems.length > 0}
      <SourceStateBadge state="attention" class="w-fit" />
    {/if}
  </div>
{:else}
  <SourceStateBadge state={summary.state} />
{/if}
