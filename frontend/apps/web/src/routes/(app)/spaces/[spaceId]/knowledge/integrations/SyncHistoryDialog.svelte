<script lang="ts">
  import { Dialog } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import type { IntegrationKnowledge } from "@intric/intric-js";
  import { onMount } from "svelte";
  import { writable, type Writable } from "svelte/store";
  import { IconHistory } from "@intric/icons/history";
  import { IconCheck } from "@intric/icons/check";
  import { IconXMark } from "@intric/icons/x-mark";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { getIntric } from "$lib/core/Intric";

  // Get intric during component initialization
  const intric = getIntric();

  interface SyncLog {
    id: string;
    sync_type: string;
    status: string;
    files_processed: number;
    files_deleted: number;
    pages_processed: number;
    folders_processed: number;
    skipped_items: number;
    error_message: string | null;
    started_at: string;
    completed_at: string | null;
    created_at: string;
    duration_seconds?: number;
    total_items_processed?: number;
  }

  export let knowledge: IntegrationKnowledge | null;
  export let open = false; // publik boolean, används av förälder

  // Declare state variables FIRST before using them in callbacks
  let syncLogs: SyncLog[] = [];
  let loading = false;
  let error: string | null = null;
  let localKnowledge: IntegrationKnowledge | null = null;
  let currentPage = 1;
  let pageSize = 10;
  let totalCount = 0;
  let totalPages = 1;
  let hasLoadedOnce = false;

  // Dialog kräver en Writable<boolean> – använd openController/isOpen enligt typerna
  let openController: Writable<boolean> = writable(open);

  // Håll boolean-propet och controllern i synk båda vägarna
  const unsub = openController.subscribe((v) => {
    if (v !== open) open = v;
    // Reset state when dialog closes
    if (!v) {
      hasLoadedOnce = false;
      syncLogs = [];
      currentPage = 1;
    }
  });
  $: if ($openController !== open) {
    openController.set(open);
  }

  onMount(() => {
    if (knowledge) {
      localKnowledge = knowledge;
      loadSyncHistory(1);
    }
    return () => unsub();
  });

  async function loadSyncHistory(page: number = 1) {
    if (!localKnowledge?.id) return;
    loading = true;
    error = null;
    try {
      const skip = (page - 1) * pageSize;
      const response = await intric.integrations.knowledge.getSyncLogs({
        knowledge: localKnowledge,
        skip,
        limit: pageSize
      });

      console.log("Sync logs response:", response);

      syncLogs = response.items || [];
      totalCount = response.total_count || 0;
      totalPages = response.total_pages || 1;
      currentPage = page;
      hasLoadedOnce = true;

      console.log("Loaded page", page, "with", syncLogs.length, "items, total:", totalCount);
    } catch (err) {
      error = err instanceof Error ? err.message : "Failed to load sync history";
      console.error("Error loading sync history:", err);
      hasLoadedOnce = true;
    } finally {
      loading = false;
    }
  }

  function goToPage(page: number) {
    if (page >= 1 && page <= totalPages) {
      loadSyncHistory(page);
    }
  }

  function formatDate(value: string): string {
    try {
      return new Date(value).toLocaleString();
    } catch {
      return value;
    }
  }

  function getDuration(log: SyncLog): string {
    if (!log.completed_at) return "-";
    try {
      const start = new Date(log.started_at).getTime();
      const end = new Date(log.completed_at).getTime();
      const seconds = Math.floor((end - start) / 1000);
      if (seconds < 60) return `${seconds}s`;
      if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
      return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
    } catch {
      return "-";
    }
  }

  function getSyncTypeLabel(syncType: string): string {
    return syncType === "full" ? m.full_sync() : m.delta_sync();
  }

  function getSyncSummary(log: SyncLog): string {
    const parts: string[] = [];

    if (log.files_processed > 0) {
      parts.push(m.file_s_synced({ count: log.files_processed }));
    }
    if (log.files_deleted > 0) {
      parts.push(m.file_s_deleted({ count: log.files_deleted }));
    }
    if (log.pages_processed > 0) {
      parts.push(m.page_s_synced({ count: log.pages_processed }));
    }
    if (log.skipped_items > 0) {
      parts.push(m.item_s_skipped({ count: log.skipped_items }));
    }

    return parts.length > 0 ? parts.join(", ") : m.no_changes();
  }

  function getPageStats() {
    let pageFiles = 0;
    let pageDeleted = 0;
    let pagePages = 0;
    let pageSyncs = 0;
    let pageSuccessfulSyncs = 0;

    for (const log of syncLogs) {
      if (log.status === "success") {
        pageFiles += log.files_processed;
        pageDeleted += log.files_deleted;
        pagePages += log.pages_processed;
        pageSuccessfulSyncs++;
      }
      pageSyncs++;
    }

    return { pageFiles, pageDeleted, pagePages, pageSyncs, pageSuccessfulSyncs };
  }

  // Ladda historik när dialogen öppnas eller när knowledge ändras
  $: if ($openController && knowledge) {
    // If knowledge changed, reset and reload
    if (localKnowledge?.id !== knowledge?.id) {
      hasLoadedOnce = false;
      syncLogs = [];
      currentPage = 1;
      localKnowledge = knowledge;
      loadSyncHistory(1);
    } else if (!hasLoadedOnce && !loading) {
      // First load for this knowledge
      localKnowledge = knowledge;
      loadSyncHistory(1);
    }
  }

  function close() {
    openController.set(false);
  }
</script>

<!-- Använd bind:openController (eller bind:isOpen) i stället för bind:open -->
<Dialog.Root bind:openController={openController}>
  <!-- Dialog.Content accepterar inte class; använd width-prop + yttre wrapper för styling -->
  <Dialog.Content width="large" form={false}>
    <div class="w-full flex flex-col gap-6">
      <!-- Header -->
      <div>
        <Dialog.Title>{m.sync_history()} - {knowledge?.name}</Dialog.Title>
      </div>

      <!-- Content area -->
      <div class="space-y-4 max-h-[60vh] overflow-y-auto pr-2">
        {#if loading}
          <div class="flex items-center justify-center py-8">
            <IconLoadingSpinner size="lg" class="animate-spin" />
            <span class="ml-2">{m.loading_available_sites()}...</span>
          </div>
        {:else if error}
          <div class="flex items-center gap-2 text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950 p-4 rounded">
            <IconXMark size="md" />
            <span>{error}</span>
          </div>
        {:else if syncLogs.length === 0}
          <div class="text-center py-8 text-secondary">
            <IconHistory size="lg" class="mx-auto mb-2 opacity-50" />
            <p>{m.integration_sync_summary_none()}</p>
          </div>
        {:else}
          <!-- Overall Statistics -->
          {(() => {
            const stats = getPageStats();
            return null;
          })()}
          <div class="bg-primary border border-default rounded-lg p-4 space-y-3">
            <div class="flex justify-between items-center">
              <div class="font-semibold text-sm">{m.overall_statistics()}</div>
              <div class="text-xs text-secondary-muted">
                {m.total_syncs()}: {totalCount}
              </div>
            </div>
            <div class="grid grid-cols-2 gap-3 text-sm">
              <div class="flex justify-between">
                <span class="text-secondary">{m.page()}:</span>
                <span class="font-medium">{currentPage} {m.per_page()}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-secondary">{m.total_syncs()}:</span>
                <span class="font-medium">{syncLogs.length}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-secondary">{m.files_synced()}:</span>
                <span class="font-medium">{getPageStats().pageFiles}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-secondary">{m.files_deleted()}:</span>
                <span class="font-medium text-red-600 dark:text-red-400">{getPageStats().pageDeleted}</span>
              </div>
              <div class="flex justify-between col-span-2">
                <span class="text-secondary">{m.pages_synced()}:</span>
                <span class="font-medium">{getPageStats().pagePages}</span>
              </div>
            </div>
          </div>
            {#each syncLogs as log (log.id)}
              <div class="border border-default rounded-lg p-3 hover:bg-hover-default transition-colors">
                <!-- Status row -->
                <div class="flex items-center justify-between mb-3">
                  <div class="flex items-center gap-2">
                    {#if log.status === "success"}
                      <IconCheck size="sm" class="text-green-600 dark:text-green-400 flex-shrink-0" />
                    {:else if log.status === "error"}
                      <IconXMark size="sm" class="text-red-600 dark:text-red-400 flex-shrink-0" />
                    {:else}
                      <IconLoadingSpinner size="sm" class="text-yellow-600 dark:text-yellow-400 animate-spin flex-shrink-0" />
                    {/if}
                    <span class="font-medium text-sm">
                      {getSyncTypeLabel(log.sync_type)}
                    </span>
                    <span
                      class="text-xs px-2 py-0.5 rounded-full font-medium"
                      class:bg-green-100={log.status === "success"}
                      class:dark:bg-green-900={log.status === "success"}
                      class:text-green-800={log.status === "success"}
                      class:dark:text-green-200={log.status === "success"}
                      class:bg-red-100={log.status === "error"}
                      class:dark:bg-red-900={log.status === "error"}
                      class:text-red-800={log.status === "error"}
                      class:dark:text-red-200={log.status === "error"}
                      class:bg-yellow-100={log.status === "in_progress"}
                      class:dark:bg-yellow-900={log.status === "in_progress"}
                      class:text-yellow-800={log.status === "in_progress"}
                      class:dark:text-yellow-200={log.status === "in_progress"}
                    >
                      {log.status}
                    </span>
                  </div>
                  <span class="text-xs text-secondary-muted flex-shrink-0">{formatDate(log.started_at)}</span>
                </div>

                <!-- Summary -->
                <div class="text-xs text-secondary mb-2">
                  {getSyncSummary(log)}
                </div>

                <!-- Duration and error -->
                <div class="flex items-center gap-4 text-xs text-secondary-muted">
                  <span>{m.duration()}: {getDuration(log)}</span>
                  {#if log.error_message}
                    <span class="text-red-600 dark:text-red-400 font-medium">{m.error()}: {log.error_message}</span>
                  {/if}
                </div>
              </div>
            {/each}
        {/if}
      </div>

      <!-- Footer -->
      <div class="flex justify-between items-center border-t border-default pt-4">
        {#if totalPages > 1}
          <div class="flex gap-2">
            <button
              disabled={currentPage === 1 || loading}
              on:click={() => goToPage(currentPage - 1)}
              class="px-3 py-2 text-sm rounded-md bg-secondary hover:bg-secondary/90 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {m.previous()}
            </button>
            <button
              disabled={currentPage === totalPages || loading}
              on:click={() => goToPage(currentPage + 1)}
              class="px-3 py-2 text-sm rounded-md bg-secondary hover:bg-secondary/90 transition-colors font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {m.next()}
            </button>
          </div>
        {/if}
        <button
          on:click={close}
          class="px-3 py-2 text-sm rounded-md bg-secondary hover:bg-secondary/90 transition-colors font-medium"
        >
          {m.close()}
        </button>
      </div>
    </div>
  </Dialog.Content>
</Dialog.Root>
