<script lang="ts">
  import { untrack } from "svelte";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import Check from "@lucide/svelte/icons/check";
  import X from "@lucide/svelte/icons/x";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors";
  import { formatDuration, formatTime } from "$lib/core/formatting/dateTime";
  import { describeSkipReason } from "$lib/features/integrations/skipReasons";
  import { isCredentialsError } from "$lib/features/integrations/sourceProblems";
  import {
    activityKind,
    appendPage,
    groupActivityByDay,
    mergeActivity,
    itemsToPage,
    mergeFirstPage,
    readSyncLogExtras,
    skippedNotListed,
    summarizeActivity,
    type ActivityKind,
    type SyncLog
  } from "$lib/features/integrations/syncActivity";
  import { m } from "$lib/paraglide/messages";
  import SourceActivityDay from "$lib/features/knowledge/components/SourceActivityDay.svelte";

  interface Props {
    items: IntegrationKnowledge[];
    /** The one folder whose history to show; null shows every folder's. */
    selectedId: string | null;
    /** Per item, changes when a sync of the item finishes, so its history reloads. */
    signatures: Record<string, string>;
    onSelect: (itemId: string | null) => void;
  }

  let { items, selectedId, signatures, onSelect }: Props = $props();

  const eneo = getEneo();
  const {
    state: { currentSpace }
  } = getSpacesManager();
  /** Per request; the endpoint caps a page, so a long history is read page by page. */
  const PAGE_SIZE = 10;

  type ItemLogs = { logs: SyncLog[]; total: number };

  let byItem = $state.raw<Record<string, ItemLogs>>({});
  let pending = $state(0);
  let error = $state<string | null>(null);
  let retry: (() => void) | null = null;
  // The latest request per item; an older answer for the item is dropped. Not reactive:
  // the effect that fetches what is missing must not rerun when a request starts.
  // eslint-disable-next-line svelte/prefer-svelte-reactivity -- see above
  const requests = new Map<string, number>();
  let requestCount = 0;

  let multiple = $derived(items.length > 1);
  let shown = $derived(selectedId ? items.filter((item) => item.id === selectedId) : items);
  let loaded = $derived(
    shown.flatMap((item) => (byItem[item.id] ? [{ item, ...byItem[item.id] }] : []))
  );
  let loading = $derived(pending > 0);
  let entries = $derived(mergeActivity(loaded));
  let days = $derived(groupActivityByDay(entries));
  let totals = $derived(summarizeActivity(entries));
  let hasMore = $derived(loaded.some((entry) => entry.total > entry.logs.length));
  let syncCount = $derived(loaded.reduce((sum, entry) => sum + entry.total, 0));

  function folderLabel(item: IntegrationKnowledge): string {
    const sameName = items.filter((other) => other.name === item.name).length > 1;
    return sameName && item.folder_path ? item.folder_path : item.name;
  }

  async function fetchPage(item: IntegrationKnowledge, skip: number) {
    const request = ++requestCount;
    requests.set(item.id, request);
    const { history: response } = await eneo.integrations.knowledge.getSyncDetails({
      knowledge: item,
      space: $currentSpace,
      offset: skip,
      limit: PAGE_SIZE
    });
    if (requests.get(item.id) !== request) return null;
    return { logs: response.items ?? [], total: response.total_count ?? 0 };
  }

  async function run(task: () => Promise<void>) {
    pending += 1;
    error = null;
    try {
      await task();
    } catch (err) {
      error = getErrorMessage(err);
      retry = () => void run(task);
    } finally {
      pending -= 1;
    }
  }

  /** Each item's newest page, kept together with the older pages it reaches. */
  function loadNewest(targets: IntegrationKnowledge[]) {
    if (targets.length === 0) return;
    void run(async () => {
      const pages = await Promise.all(
        targets.map(async (item) => ({ item, page: await fetchPage(item, 0) }))
      );
      const next = { ...byItem };
      for (const { item, page } of pages) {
        if (!page) continue;
        next[item.id] = {
          logs: mergeFirstPage(next[item.id]?.logs, page.logs, page.total),
          total: page.total
        };
      }
      byItem = next;
    });
  }

  function loadOlder() {
    if (loading) return;
    const targets = itemsToPage(loaded);
    void run(async () => {
      const pages = await Promise.all(
        targets.map(async ({ item, logs }) => ({ item, page: await fetchPage(item, logs.length) }))
      );
      const next = { ...byItem };
      for (const { item, page } of pages) {
        const current = next[item.id];
        if (!page || !current) continue;
        const logs = appendPage(current.logs, page.logs);
        // Nothing new means the newest logs moved under the paging; stop rather than loop.
        next[item.id] = {
          logs,
          total: logs.length > current.logs.length ? page.total : logs.length
        };
      }
      byItem = next;
    });
  }

  // A folder's history is first fetched when it is shown.
  $effect(() => {
    const missing = shown.filter((item) => !requests.has(item.id));
    untrack(() => loadNewest(missing));
  });

  let seenSignatures = untrack(() => signatures);
  $effect(() => {
    const current = signatures;
    untrack(() => {
      const changed = items.filter(
        (item) => item.id in byItem && current[item.id] !== seenSignatures[item.id]
      );
      seenSignatures = current;
      loadNewest(changed);
    });
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
        const add = (
          count: number,
          one: () => string,
          other: (inputs: { count: number }) => string
        ) => {
          if (count > 0) parts.push(count === 1 ? one() : other({ count }));
        };
        add(
          log.files_processed,
          m.integration_activity_files_synced_one,
          m.integration_activity_files_synced_other
        );
        add(
          log.pages_processed,
          m.integration_activity_pages_synced_one,
          m.integration_activity_pages_synced_other
        );
        add(
          log.files_deleted,
          m.integration_activity_files_deleted_one,
          m.integration_activity_files_deleted_other
        );
        add(
          log.skipped_items,
          m.integration_activity_items_skipped_one,
          m.integration_activity_items_skipped_other
        );
        if (parts.length === 0) {
          add(
            extras.unchangedItems,
            m.integration_activity_items_unchanged_one,
            m.integration_activity_items_unchanged_other
          );
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

  const changeStyle = {
    added: "text-positive-stronger",
    updated: "text-accent-stronger",
    deleted: "text-negative-stronger"
  } as const;

  function changeLabel(change: "added" | "updated" | "deleted"): string {
    switch (change) {
      case "added":
        return m.integration_activity_change_added();
      case "updated":
        return m.integration_activity_change_updated();
      case "deleted":
        return m.integration_activity_change_deleted();
    }
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
    class="flex min-w-0 flex-[999_1_32rem] flex-col gap-6"
  >
    <!-- The timeline of every folder stops where the busiest runs out; a quiet folder's
         older syncs are reached by choosing it. -->
    {#if multiple}
      <div class="flex flex-wrap items-center gap-2 text-sm">
        <label for="activity-folder" class="text-secondary">{m.integration_source_folder()}</label>
        <select
          id="activity-folder"
          class="border-default bg-primary text-default rounded-md border px-2 py-1.5 text-sm"
          value={selectedId ?? ""}
          onchange={(event) => onSelect(event.currentTarget.value || null)}
        >
          <option value="">{m.integration_source_all_folders()}</option>
          {#each items as item (item.id)}
            <option value={item.id}>{folderLabel(item)}</option>
          {/each}
        </select>
      </div>
    {/if}

    {#if error}
      <div
        class="text-negative-stronger bg-negative-dimmer flex flex-wrap items-center gap-3 rounded p-4 text-sm"
        role="alert"
      >
        <span>{m.sync_history_load_failed()}: {error}</span>
        <Button variant="outline" size="sm" onclick={() => retry?.()}>{m.retry()}</Button>
      </div>
    {/if}

    {#if loading && loaded.length === 0}
      <div class="text-secondary flex items-center gap-2 text-sm" role="status">
        <IconLoadingSpinner size="sm" class="motion-safe:animate-spin" />
        <span>{m.loading_sync_history()}</span>
      </div>
    {:else if !error && entries.length === 0}
      <p class="text-secondary py-6 text-sm">{m.integration_sync_summary_none()}</p>
    {/if}

    {#each days as day (day.day)}
      <SourceActivityDay date={day.entries[0].log.started_at}>
        {#each day.entries as { log, item } (log.id)}
          {@const kind = activityKind(log)}
          {@const extras = readSyncLogExtras(log)}
          {@const failure = failureText(log)}
          {@const took = duration(log)}
          <li class="border-dimmer flex gap-3 border-t py-3">
            <time
              class="text-secondary w-11 shrink-0 pt-1.5 text-xs tabular-nums"
              datetime={log.started_at}
            >
              {formatTime(log.started_at)}
            </time>
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
              <p class="font-medium">{title(log, kind)}</p>
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
                  multiple && !selectedId ? item.name : null,
                  log.sync_type === "full" ? m.full_sync() : m.delta_sync(),
                  took
                ]
                  .filter((part) => part !== null)
                  .join(" · ")}
              </p>
              {#if extras.changedFiles.length > 0 || log.skipped_details?.length > 0}
                {@const notListed =
                  skippedNotListed(log) +
                  Math.max(0, extras.changedTotal - extras.changedFiles.length)}
                <details class="text-sm">
                  <summary
                    class="text-secondary focus-visible:ring-stronger w-fit cursor-pointer rounded text-xs hover:underline focus-visible:ring-2 focus-visible:outline-none"
                  >
                    {extras.changedTotal + log.skipped_items === 1
                      ? m.integration_activity_show_files_one()
                      : m.integration_activity_show_files_other({
                          count: extras.changedTotal + log.skipped_items
                        })}
                  </summary>
                  <ul class="mt-1 flex flex-col gap-0.5 pl-1 text-xs">
                    <!-- The same file name recurs across folders, so the key needs the position. -->
                    {#each extras.changedFiles as change, index (`c${index}:${change.file}`)}
                      <li class="flex gap-2">
                        <span class="w-20 shrink-0 font-medium {changeStyle[change.change]}"
                          >{changeLabel(change.change)}</span
                        >
                        <span class="text-primary min-w-0 break-all">{change.file}</span>
                      </li>
                    {/each}
                    {#each log.skipped_details ?? [] as detail, index (`s${index}:${detail.file}`)}
                      <li class="flex gap-2">
                        <span class="text-warning-stronger w-20 shrink-0 font-medium"
                          >{m.integration_activity_change_skipped()}</span
                        >
                        <span class="min-w-0 break-all">
                          <span class="text-primary">{detail.file}</span>
                          <span class="text-secondary">– {describeSkipReason(detail)}</span>
                        </span>
                      </li>
                    {/each}
                    {#if notListed > 0}
                      <li class="text-secondary italic">
                        {m.skipped_and_n_more({ count: notListed })}
                      </li>
                    {:else if extras.skippedTruncated}
                      <li class="text-secondary italic">{m.skipped_list_truncated()}</li>
                    {/if}
                  </ul>
                </details>
              {/if}
            </div>
          </li>
        {/each}
      </SourceActivityDay>
    {/each}

    {#if hasMore}
      <!-- Stays focusable while loading: a focused button that turns disabled drops focus to the body. -->
      <Button
        variant="outline"
        class="w-fit {loading ? 'pointer-events-none opacity-50' : ''}"
        aria-disabled={loading}
        aria-busy={loading}
        onclick={loadOlder}
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
        {totals.syncs === 1
          ? m.integration_activity_totals_heading_one()
          : m.integration_activity_totals_heading_other({ count: totals.syncs })}
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
