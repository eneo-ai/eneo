<script lang="ts">
  import { untrack } from "svelte";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { m } from "$lib/paraglide/messages";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconHistory } from "@eneo/icons/history";
  import { IconCheck } from "@eneo/icons/check";
  import { IconXMark } from "@eneo/icons/x-mark";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors";
  import {
    readSyncLogExtras,
    skippedNotListed,
    summarizeSyncLogPage,
    type SyncLog
  } from "./syncHistory";

  interface Props {
    knowledge: IntegrationKnowledge | null;
    open?: boolean;
  }

  let { knowledge, open = $bindable(false) }: Props = $props();

  const eneo = getEneo();
  const pageSize = 10;

  let syncLogs = $state<SyncLog[]>([]);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let currentPage = $state(1);
  let totalCount = $state(0);
  let totalPages = $state(1);
  let loadedKnowledgeId = $state<string | null>(null);
  let loadGeneration = 0;

  let pageStats = $derived(summarizeSyncLogPage(syncLogs));

  function reset() {
    loadGeneration += 1;
    syncLogs = [];
    loading = false;
    error = null;
    currentPage = 1;
    totalCount = 0;
    totalPages = 1;
    loadedKnowledgeId = null;
  }

  async function loadSyncHistory(target: IntegrationKnowledge, page: number) {
    const generation = ++loadGeneration;
    loading = true;
    error = null;
    try {
      const response = await eneo.integrations.knowledge.getSyncLogs({
        knowledge: target,
        skip: (page - 1) * pageSize,
        limit: pageSize
      });
      if (generation !== loadGeneration) return;
      syncLogs = response.items ?? [];
      totalCount = response.total_count ?? 0;
      totalPages = response.total_pages ?? 1;
      currentPage = page;
    } catch (err) {
      if (generation !== loadGeneration) return;
      error = `${m.sync_history_load_failed()}: ${getErrorMessage(err)}`;
    } finally {
      if (generation === loadGeneration) loading = false;
    }
  }

  function goToPage(page: number) {
    if (!knowledge || page < 1 || page > totalPages) return;
    void loadSyncHistory(knowledge, page);
  }

  $effect(() => {
    if (!open) {
      reset();
      return;
    }
    const target = knowledge;
    if (!target || target.id === untrack(() => loadedKnowledgeId)) return;
    loadedKnowledgeId = target.id;
    void loadSyncHistory(target, 1);
  });

  function formatDate(value: string): string {
    return Number.isNaN(new Date(value).getTime()) ? value : formatDateTime(value);
  }

  function getDuration(log: SyncLog): string {
    if (!log.completed_at) return "-";
    const start = new Date(log.started_at).getTime();
    const end = new Date(log.completed_at).getTime();
    if (Number.isNaN(start) || Number.isNaN(end)) return "-";
    const seconds = Math.max(0, Math.floor((end - start) / 1000));
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  }

  function getSyncTypeLabel(syncType: string): string {
    return syncType === "full" ? m.full_sync() : m.delta_sync();
  }

  function getStatusLabel(status: string): string {
    switch (status) {
      case "success":
        return m.success();
      case "error":
        return m.error();
      case "in_progress":
        return m.in_progress();
      default:
        return m.unknown();
    }
  }

  function getSyncSummary(log: SyncLog): string {
    const parts: string[] = [];
    const extras = readSyncLogExtras(log);

    if (log.files_processed > 0) parts.push(m.file_s_synced({ count: log.files_processed }));
    if (log.files_deleted > 0) parts.push(m.file_s_deleted({ count: log.files_deleted }));
    if (log.pages_processed > 0) parts.push(m.page_s_synced({ count: log.pages_processed }));
    if (extras.unchangedItems > 0) parts.push(m.item_s_unchanged({ count: extras.unchangedItems }));
    if (log.skipped_items > 0) parts.push(m.item_s_skipped({ count: log.skipped_items }));

    return parts.length > 0 ? parts.join(", ") : m.no_changes();
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class={dialogLayout.content("large")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.sync_history()} - {knowledge?.name}</Dialog.Title>
    </Dialog.Header>

    <div class={dialogLayout.body}>
      {#if loading}
        <div class="flex items-center justify-center py-8" role="status">
          <IconLoadingSpinner size="lg" class="animate-spin" />
          <span class="ml-2">{m.loading_sync_history()}</span>
        </div>
      {:else if error}
        <div
          class="text-negative-stronger bg-negative-dimmer flex items-center gap-2 rounded p-4"
          role="alert"
        >
          <IconXMark size="md" />
          <span>{error}</span>
        </div>
      {:else if syncLogs.length === 0}
        <div class="text-secondary py-8 text-center">
          <IconHistory size="lg" class="mx-auto mb-2 opacity-50" />
          <p>{m.integration_sync_summary_none()}</p>
        </div>
      {:else}
        <div class="bg-primary border-default space-y-3 rounded-lg border p-4">
          <div class="flex items-center justify-between">
            <div class="text-sm font-semibold">{m.page_statistics()}</div>
            <div class="text-muted text-xs">
              {m.total_syncs()}: {totalCount}
            </div>
          </div>
          <div class="grid grid-cols-2 gap-3 text-sm">
            <div class="flex justify-between">
              <span class="text-secondary">{m.page()}:</span>
              <span class="font-medium">
                {m.page_x_of_y({ x: currentPage, y: totalPages })}
              </span>
            </div>
            <div class="flex justify-between">
              <span class="text-secondary">{m.syncs_on_page()}:</span>
              <span class="font-medium">{pageStats.syncs}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-secondary">{m.files_synced()}:</span>
              <span class="font-medium">{pageStats.files}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-secondary">{m.files_deleted()}:</span>
              <span class="text-negative-default font-medium">{pageStats.deleted}</span>
            </div>
            <div class="col-span-2 flex justify-between">
              <span class="text-secondary">{m.pages_synced()}:</span>
              <span class="font-medium">{pageStats.pages}</span>
            </div>
          </div>
        </div>
        {#each syncLogs as log (log.id)}
          {@const extras = readSyncLogExtras(log)}
          {@const notListed = skippedNotListed(log)}
          <div
            class="border-default hover:bg-hover-default rounded-lg border p-3 transition-colors"
          >
            <div class="mb-3 flex items-center justify-between">
              <div class="flex items-center gap-2">
                {#if log.status === "success"}
                  <IconCheck size="sm" class="text-positive-default flex-shrink-0" />
                {:else if log.status === "error"}
                  <IconXMark size="sm" class="text-negative-default flex-shrink-0" />
                {:else}
                  <IconLoadingSpinner
                    size="sm"
                    class="text-warning-default flex-shrink-0 animate-spin"
                  />
                {/if}
                <span class="text-sm font-medium">
                  {getSyncTypeLabel(log.sync_type)}
                </span>
                <span
                  class="rounded-full px-2 py-0.5 text-xs font-medium"
                  class:bg-positive-dimmer={log.status === "success"}
                  class:text-positive-stronger={log.status === "success"}
                  class:bg-negative-dimmer={log.status === "error"}
                  class:text-negative-stronger={log.status === "error"}
                  class:bg-warning-dimmer={log.status === "in_progress"}
                  class:text-warning-stronger={log.status === "in_progress"}
                >
                  {getStatusLabel(log.status)}
                </span>
              </div>
              <span class="text-muted flex-shrink-0 text-xs">{formatDate(log.started_at)}</span>
            </div>

            <div class="text-secondary mb-2 text-xs">
              {getSyncSummary(log)}
            </div>

            {#if extras.reconcileWarning}
              <p class="text-warning-stronger mb-2 text-xs">
                <span class="font-medium">{m.sync_reconcile_warning()}:</span>
                {extras.reconcileWarning}
              </p>
            {/if}

            {#if log.skipped_items > 0 && log.skipped_details?.length > 0}
              <details class="mb-2">
                <summary class="text-warning-stronger cursor-pointer text-xs hover:underline">
                  {m.item_s_skipped({ count: log.skipped_items })}
                </summary>
                <ul class="text-secondary mt-1 ml-4 space-y-0.5 text-xs">
                  <!-- The same file name recurs across folders, so the key needs the position. -->
                  {#each log.skipped_details as detail, index (`${index}:${detail.file}`)}
                    <li class="flex gap-1">
                      <span class="text-primary max-w-[200px] font-medium break-all"
                        >{detail.file}</span
                      >
                      <span class="text-muted">&mdash;</span>
                      <span class="text-muted">{detail.reason}</span>
                    </li>
                  {/each}
                  {#if extras.skippedTruncated}
                    <li class="text-muted italic">
                      {notListed > 0
                        ? m.skipped_and_n_more({ count: notListed })
                        : m.skipped_list_truncated()}
                    </li>
                  {/if}
                </ul>
              </details>
            {/if}

            <div class="text-muted flex items-center gap-4 text-xs">
              <span>{m.duration()}: {getDuration(log)}</span>
              {#if log.error_message}
                <span class="text-negative-default font-medium"
                  >{m.error()}: {log.error_message}</span
                >
              {/if}
            </div>
          </div>
        {/each}
      {/if}
    </div>

    <Dialog.Footer class={dialogLayout.footer}>
      {#if totalPages > 1}
        <div class="flex gap-2 sm:mr-auto">
          <Button
            variant="outline"
            disabled={currentPage === 1 || loading}
            onclick={() => goToPage(currentPage - 1)}
          >
            {m.previous()}
          </Button>
          <Button
            variant="outline"
            disabled={currentPage === totalPages || loading}
            onclick={() => goToPage(currentPage + 1)}
          >
            {m.next()}
          </Button>
        </div>
      {/if}
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.close()}</Dialog.Close>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
