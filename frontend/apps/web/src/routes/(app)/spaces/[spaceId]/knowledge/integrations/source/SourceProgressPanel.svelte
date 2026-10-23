<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { formatRelativeTime } from "$lib/core/formatting/dateTime";
  import SyncProgressBar from "$lib/features/integrations/components/SyncProgressBar.svelte";
  import type {
    SyncProgressPhase,
    SyncProgressSummary
  } from "$lib/features/integrations/syncProgress";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    progress: SyncProgressSummary;
    sourceName: string;
    /** No item of the source has finished a sync before. */
    firstSync: boolean;
    /** The file each syncing folder reads right now, for a source of several folders. */
    nowReading?: { folder: string; file: string }[];
  }

  let { progress, sourceName, firstSync, nowReading = [] }: Props = $props();

  const phases: { id: SyncProgressPhase; label: () => string }[] = [
    { id: "discovering", label: () => m.integration_progress_phase_discovering() },
    { id: "processing", label: () => m.integration_progress_phase_processing() },
    { id: "finishing", label: () => m.integration_progress_phase_finishing() }
  ];

  let currentPhase = $derived(phases.findIndex((phase) => phase.id === progress.phase));
  let readable = $derived(progress.indexed + progress.unchanged);
  let remaining = $derived(
    progress.total === null ? null : Math.max(0, progress.total - progress.done)
  );
</script>

<section
  aria-labelledby="sync-progress-heading"
  class="border-accent-default bg-accent-dimmer/40 flex flex-col gap-4 rounded-lg border p-4"
>
  <div class="flex flex-wrap items-baseline justify-between gap-2">
    <div class="flex items-center gap-2">
      <IconLoadingSpinner size="sm" class="text-accent-default motion-safe:animate-spin" />
      <h2 id="sync-progress-heading" class="text-base font-semibold">
        {firstSync ? m.integration_progress_first_sync() : m.integration_progress_sync_running()}
      </h2>
    </div>
    <span class="text-secondary text-sm">
      {m.integration_progress_started({ time: formatRelativeTime(progress.startedAt) })}
      {#if progress.syncing > 1}
        · {m.integration_progress_folders_syncing({ count: progress.syncing })}
      {/if}
    </span>
  </div>

  <div class="flex flex-col gap-2">
    <SyncProgressBar
      {progress}
      size="md"
      label={m.integration_progress_label({ name: sourceName })}
    />
    <ul class="text-secondary flex flex-wrap gap-x-5 gap-y-1 text-sm">
      <li class="flex items-center gap-1.5">
        <span class="bg-accent-default size-2.5 rounded-sm" aria-hidden="true"></span>
        {m.integration_progress_readable({ count: readable })}
      </li>
      {#if progress.skipped > 0}
        <li class="flex items-center gap-1.5">
          <span class="bg-warning-default size-2.5 rounded-sm" aria-hidden="true"></span>
          {m.integration_progress_skipped({ count: progress.skipped })}
        </li>
      {/if}
      {#if remaining !== null}
        <li class="flex items-center gap-1.5">
          <span class="bg-tertiary border-default size-2.5 rounded-sm border" aria-hidden="true"
          ></span>
          {m.integration_progress_remaining({ count: remaining })}
        </li>
      {/if}
    </ul>
  </div>

  <ol class="grid gap-2 sm:grid-cols-3" aria-label={m.integration_progress_steps()}>
    {#each phases as phase, index (phase.id)}
      {@const done = index < currentPhase}
      {@const active = index === currentPhase}
      <li
        aria-current={active ? "step" : undefined}
        class="bg-primary flex items-center gap-2 rounded-md border px-3 py-2 text-sm {active
          ? 'border-accent-default'
          : 'border-default'} {done || active ? '' : 'text-secondary'}"
      >
        {#if done}
          <Check class="text-positive-default size-4 shrink-0" aria-hidden="true" />
          <span class="sr-only">{m.integration_progress_step_done()}</span>
        {:else if active}
          <IconLoadingSpinner
            size="sm"
            class="text-accent-default shrink-0 motion-safe:animate-spin"
          />
        {:else}
          <span class="border-strongest size-3.5 shrink-0 rounded-full border" aria-hidden="true"
          ></span>
        {/if}
        <span class:font-medium={active}>{phase.label()}</span>
      </li>
    {/each}
  </ol>

  {#if nowReading.length > 0}
    <ul class="flex flex-col gap-1 text-sm">
      {#each nowReading.slice(0, 3) as reading, index (index)}
        <li class="flex min-w-0 items-center gap-2">
          <IconLoadingSpinner
            size="sm"
            class="text-accent-default shrink-0 motion-safe:animate-spin"
          />
          <span class="text-secondary shrink-0">
            {m.integration_progress_reading_in({ folder: reading.folder })}
          </span>
          <span class="min-w-0 truncate font-medium">{reading.file}</span>
        </li>
      {/each}
    </ul>
  {/if}

  <p class="text-secondary text-sm">{m.integration_progress_leave_page_hint()}</p>
</section>
