<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import Equal from "@lucide/svelte/icons/equal";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { describeSkipReason } from "$lib/features/integrations/skipReasons";
  import type { IntegrationSyncProgress } from "$lib/features/integrations/syncProgress";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    progress: IntegrationSyncProgress;
  }

  let { progress }: Props = $props();

  /** Enough to see the sync move without pushing the documents below the fold. */
  const SHOWN = 5;

  let recent = $derived((progress.recent ?? []).slice(0, SHOWN));
</script>

{#if progress.current || recent.length > 0}
  <section
    aria-labelledby="live-sync-{progress.integration_knowledge_id}"
    class="border-accent-default/40 flex flex-col rounded-lg border"
  >
    <h3
      id="live-sync-{progress.integration_knowledge_id}"
      class="text-secondary border-default border-b px-4 py-2 text-xs font-semibold tracking-wide uppercase"
    >
      {m.integration_live_heading()}
    </h3>
    <ul class="flex flex-col text-sm">
      {#if progress.current}
        <li class="flex items-center gap-3 px-4 py-2">
          <IconLoadingSpinner
            size="sm"
            class="text-accent-default shrink-0 motion-safe:animate-spin"
          />
          <span class="min-w-0 flex-1 truncate font-medium">{progress.current}</span>
          <span class="text-accent-stronger shrink-0 text-xs">{m.integration_live_reading()}</span>
        </li>
      {/if}
      {#each recent as file, index (`${index}:${file.name}`)}
        <li class="border-dimmer flex items-center gap-3 border-t px-4 py-2">
          {#if file.outcome === "indexed"}
            <Check class="text-positive-default size-4 shrink-0" aria-hidden="true" />
          {:else if file.outcome === "unchanged"}
            <Equal class="text-secondary size-4 shrink-0" aria-hidden="true" />
          {:else}
            <TriangleAlert class="text-warning-default size-4 shrink-0" aria-hidden="true" />
          {/if}
          <span class="flex min-w-0 flex-1 flex-col">
            <span class="truncate">{file.name}</span>
            {#if file.outcome === "skipped" && file.reason}
              <span class="text-secondary text-xs break-words">
                {describeSkipReason(file)}
              </span>
            {/if}
          </span>
          <span
            class="shrink-0 text-xs {file.outcome === 'skipped'
              ? 'text-warning-stronger'
              : 'text-secondary'}"
          >
            {file.outcome === "indexed"
              ? m.integration_live_indexed()
              : file.outcome === "unchanged"
                ? m.integration_live_unchanged()
                : m.integration_live_skipped()}
          </span>
        </li>
      {/each}
    </ul>
  </section>
{/if}
