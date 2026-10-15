<script lang="ts">
  import { untrack } from "svelte";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import Check from "@lucide/svelte/icons/check";
  import X from "@lucide/svelte/icons/x";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors";
  import { formatDateMedium, formatDuration, formatTime } from "$lib/core/formatting/dateTime";
  import { describeSkipReason } from "$lib/features/integrations/skipReasons";
  import { isCredentialsError } from "$lib/features/integrations/sourceProblems";
  import {
    activityKind,
    groupActivityByDay,
    mergeActivity,
    readSyncLogExtras,
    skippedNotListed,
    summarizeActivity,
    type ActivityKind,
    type SyncLog
  } from "$lib/features/integrations/syncActivity";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    items: IntegrationKnowledge[];
    /** The source has more than one item, so each entry names its folder. */
    showFolders: boolean;
    /** Changes when a sync of the source finishes, so the timeline reloads. */
    refreshKey: string;
  }

  let { items, showFolders, refreshKey }: Props = $props();

  const eneo = getEneo();
  const PAGE_SIZE = 10;

  let limit = $state(PAGE_SIZE);
  let loaded = $state<{ item: IntegrationKnowledge; logs: SyncLog[]; total: number }[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let generation = 0;

  let entries = $derived(mergeActivity(loaded));
  let days = $derived(groupActivityByDay(entries));
  let totals = $derived(summarizeActivity(entries));
  let hasMore = $derived(loaded.some((entry) => entry.total > entry.logs.length));
  let syncCount = $derived(loaded.reduce((sum, entry) => sum + entry.total, 0));

  async function load(nextLimit: number) {
    const current = ++generation;
    loading = true;
    error = null;
    try {
      const results = await Promise.all(
        items.map(async (item) => {
          const response = await eneo.integrations.knowledge.getSyncLogs({
            knowledge: item,
            skip: 0,
            limit: nextLimit
          });
          return { item, logs: response.items ?? [], total: response.total_count ?? 0 };
        })
      );
      if (current !== generation) return;
      loaded = results;
      limit = nextLimit;
    } catch (err) {
      if (current !== generation) return;
      error = getErrorMessage(err);
    } finally {
      if (current === generation) loading = false;
    }
  }

  $effect(() => {
    void refreshKey;
    untrack(() => void load(limit));
  });

  function title(log: SyncLog, kind: ActivityKind): string {
    switch (kind) {
      case "failed":
        return m.integration_activity_failed();
      case "running":
        return m.integration_activity_running();
      case "unchanged":
        return m.integration_activity_unchanged();
      case "changed": {
        const parts: string[] = [];
        const extras = readSyncLogExtras(log);
        if (log.files_processed > 0) parts.push(m.file_s_synced({ count: log.files_processed }));
        if (log.pages_processed > 0) parts.push(m.page_s_synced({ count: log.pages_processed }));
        if (log.files_deleted > 0) parts.push(m.file_s_deleted({ count: log.files_deleted }));
        if (log.skipped_items > 0) parts.push(m.item_s_skipped({ count: log.skipped_items }));
        if (parts.length === 0 && extras.unchangedItems > 0) {
          parts.push(m.item_s_unchanged({ count: extras.unchangedItems }));
        }
        return parts.join(", ");
      }
    }
  }

  function failureText(log: SyncLog): string | null {
    if (!log.error_message) return null;
    return isCredentialsError(log.error_message)
      ? m.integration_problem_credentials_title()
      : log.error_message;
  }

  function duration(log: SyncLog): string | null {
    if (!log.completed_at) return null;
    const ms = new Date(log.completed_at).getTime() - new Date(log.started_at).getTime();
    return Number.isNaN(ms) ? null : formatDuration(Math.max(ms, 1000));
  }

  const iconStyles: Record<ActivityKind, string> = {
    failed: "bg-negative-dimmer text-negative-stronger",
    running: "bg-accent-dimmer text-accent-stronger",
    changed: "bg-positive-dimmer text-positive-stronger",
    unchanged: "bg-secondary text-secondary"
  };
</script>

<div class="flex flex-wrap items-start gap-8">
  <section
    aria-label={m.integration_activity_events()}
    class="flex max-w-3xl min-w-0 flex-[999_1_32rem] flex-col gap-6"
  >
    {#if error}
      <div
        class="text-negative-stronger bg-negative-dimmer flex flex-wrap items-center gap-3 rounded p-4 text-sm"
        role="alert"
      >
        <span>{m.sync_history_load_failed()}: {error}</span>
        <Button variant="outline" size="sm" onclick={() => load(limit)}>{m.retry()}</Button>
      </div>
    {/if}

    {#if loading && loaded.length === 0}
      <div class="text-secondary flex items-center gap-2 text-sm" role="status">
        <IconLoadingSpinner size="sm" class="animate-spin" />
        <span>{m.loading_sync_history()}</span>
      </div>
    {:else if !error && entries.length === 0}
      <p class="text-secondary py-6 text-sm">{m.integration_sync_summary_none()}</p>
    {/if}

    {#each days as day (day.day)}
      <section aria-labelledby="activity-day-{day.day}" class="flex flex-col">
        <h2
          id="activity-day-{day.day}"
          class="text-secondary pb-2 text-xs font-semibold tracking-wide uppercase"
        >
          {formatDateMedium(day.entries[0].log.started_at)}
        </h2>
        <ol class="flex flex-col">
          {#each day.entries as { log, item } (log.id)}
            {@const kind = activityKind(log)}
            {@const extras = readSyncLogExtras(log)}
            {@const failure = failureText(log)}
            {@const took = duration(log)}
            <li class="border-dimmer flex gap-3 border-t py-3">
              <span
                class="flex size-7 shrink-0 items-center justify-center rounded-full {iconStyles[
                  kind
                ]}"
                aria-hidden="true"
              >
                {#if kind === "failed"}
                  <X class="size-3.5" />
                {:else if kind === "running"}
                  <IconLoadingSpinner size="sm" class="motion-safe:animate-spin" />
                {:else}
                  <Check class="size-3.5" />
                {/if}
              </span>
              <div class="flex min-w-0 flex-1 flex-col gap-1">
                <div class="flex flex-wrap items-baseline justify-between gap-x-3">
                  <p class="font-medium">{title(log, kind)}</p>
                  <time class="text-secondary text-xs tabular-nums" datetime={log.started_at}>
                    {formatTime(log.started_at)}
                  </time>
                </div>
                {#if failure}
                  <p class="text-negative-stronger text-sm break-words">{failure}</p>
                {/if}
                {#if extras.reconcileWarning}
                  <p class="text-warning-stronger text-sm">
                    <span class="font-medium">{m.sync_reconcile_warning()}:</span>
                    {extras.reconcileWarning}
                  </p>
                {/if}
                <p class="text-secondary text-xs">
                  {[
                    showFolders ? item.name : null,
                    log.sync_type === "full" ? m.full_sync() : m.delta_sync(),
                    took
                  ]
                    .filter((part) => part !== null)
                    .join(" · ")}
                </p>
                {#if log.skipped_items > 0 && log.skipped_details?.length > 0}
                  {@const notListed = skippedNotListed(log)}
                  <details class="text-sm">
                    <summary
                      class="text-warning-stronger focus-visible:ring-stronger w-fit cursor-pointer rounded text-xs hover:underline focus-visible:ring-2 focus-visible:outline-none"
                    >
                      {m.integration_activity_show_skipped({ count: log.skipped_items })}
                    </summary>
                    <ul class="text-secondary mt-1 flex flex-col gap-0.5 pl-4 text-xs">
                      <!-- The same file name recurs across folders, so the key needs the position. -->
                      {#each log.skipped_details as detail, index (`${index}:${detail.file}`)}
                        <li>
                          <span class="text-primary break-all">{detail.file}</span>
                          – {describeSkipReason(detail.reason)}
                        </li>
                      {/each}
                      {#if extras.skippedTruncated || notListed > 0}
                        <li class="italic">
                          {notListed > 0
                            ? m.skipped_and_n_more({ count: notListed })
                            : m.skipped_list_truncated()}
                        </li>
                      {/if}
                    </ul>
                  </details>
                {/if}
              </div>
            </li>
          {/each}
        </ol>
      </section>
    {/each}

    {#if hasMore}
      <Button
        variant="outline"
        class="w-fit"
        disabled={loading}
        aria-busy={loading}
        onclick={() => load(limit + PAGE_SIZE)}
      >
        {m.integration_activity_show_older()}
      </Button>
    {/if}
  </section>

  {#if entries.length > 0}
    <aside
      aria-labelledby="activity-totals"
      class="border-default flex flex-[1_1_16rem] flex-col gap-3 rounded-lg border p-4 lg:max-w-xs"
    >
      <h2 id="activity-totals" class="text-sm font-semibold">
        {m.integration_activity_totals_heading({ count: totals.syncs })}
      </h2>
      {#if syncCount > totals.syncs}
        <p class="text-secondary -mt-2 text-xs">
          {m.integration_activity_totals_of_all({ total: syncCount })}
        </p>
      {/if}
      <dl class="grid grid-cols-2 gap-3">
        <div>
          <dt class="text-secondary text-xs">{m.integration_activity_totals_failed()}</dt>
          <dd
            class="text-lg font-semibold tabular-nums {totals.failed > 0
              ? 'text-negative-stronger'
              : ''}"
          >
            {totals.failed}
          </dd>
        </div>
        <div>
          <dt class="text-secondary text-xs">{m.integration_activity_totals_changed()}</dt>
          <dd class="text-lg font-semibold tabular-nums">{totals.changedFiles}</dd>
        </div>
        <div>
          <dt class="text-secondary text-xs">{m.integration_activity_totals_unchanged()}</dt>
          <dd class="text-lg font-semibold tabular-nums">{totals.unchanged}</dd>
        </div>
        <div>
          <dt class="text-secondary text-xs">{m.integration_activity_totals_deleted()}</dt>
          <dd class="text-lg font-semibold tabular-nums">{totals.deleted}</dd>
        </div>
      </dl>
    </aside>
  {/if}
</div>
