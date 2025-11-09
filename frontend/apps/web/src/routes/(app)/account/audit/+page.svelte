<script lang="ts">
  import { onMount } from "svelte";
  import { browser } from "$app/environment";
  import { Page } from "$lib/components/layout";
  import { getIntric } from "$lib/core/Intric";
  import { Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import type { components } from "@intric/intric-js/types/schema";

  type AuditLogResponse = components["schemas"]["AuditLogResponse"];

  const intric = getIntric();

  let logs: AuditLogResponse[] = [];
  let totalCount = 0;
  let page = $state(1);
  let pageSize = 100;
  let totalPages = 0;
  let loading = $state(true);
  let error = $state("");

  async function loadAuditLogs() {
    loading = true;
    error = "";

    try {
      const response = await intric.audit.list({
        page: page,
        page_size: pageSize,
      });

      logs = response.logs;
      totalCount = response.total_count;
      page = response.page;
      pageSize = response.page_size;
      totalPages = response.total_pages;
    } catch (err: any) {
      console.error("Error loading audit logs:", err);
      error = err.message || "Failed to load audit logs";
    } finally {
      loading = false;
    }
  }

  async function exportToCSV() {
    if (!browser) return;

    try {
      // Call our server endpoint which proxies to the backend with auth
      const response = await fetch("/account/audit/export", {
        method: "GET",
      });

      if (!response.ok) {
        throw new Error("Failed to export audit logs");
      }

      const blob = await response.blob();
      const filename = `audit_logs_${new Date().toISOString()}.csv`;

      if (window.showSaveFilePicker) {
        const handle = await window.showSaveFilePicker({ suggestedName: filename });
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
      } else {
        const a = document.createElement("a");
        a.download = filename;
        a.href = URL.createObjectURL(blob);
        a.click();
        setTimeout(() => {
          URL.revokeObjectURL(a.href);
        }, 1500);
      }
    } catch (err) {
      console.error("Export failed:", err);
      alert("Failed to export audit logs");
    }
  }

  function formatDate(timestamp: string): string {
    return new Date(timestamp).toLocaleString();
  }

  function nextPage() {
    if (page < totalPages) {
      page++;
      loadAuditLogs();
    }
  }

  function prevPage() {
    if (page > 1) {
      page--;
      loadAuditLogs();
    }
  }

  onMount(() => {
    loadAuditLogs();
  });
</script>

<svelte:head>
  <title>Eneo.ai – Audit Logs</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title="Audit Logs"></Page.Title>
    <Button on:click={exportToCSV} variant="outlined">
      Export to CSV
    </Button>
  </Page.Header>
  <Page.Main>
    <div class="mb-6">
      <p class="text-muted text-sm">
        View and export your personal audit trail for compliance and security monitoring.
      </p>
    </div>

    {#if error}
      <div class="mb-4 rounded border border-red-400 bg-red-100 px-4 py-3 text-red-700">
        {error}
      </div>
    {/if}

    {#if loading}
      <div class="py-8 text-center">
        <p class="text-muted">Loading audit logs...</p>
      </div>
    {:else}
      <div class="mb-4">
        <p class="text-muted text-sm">
          Showing {logs.length} of {totalCount} audit logs
        </p>
      </div>

      <div class="border-default overflow-hidden rounded-lg border shadow-sm">
        <div class="overflow-x-auto">
          <table class="w-full">
            <thead class="bg-subtle border-b border-default">
              <tr>
                <th class="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider w-[15%]">
                  Timestamp
                </th>
                <th class="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider w-[15%]">
                  Action
                </th>
                <th class="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider w-[40%]">
                  Description
                </th>
                <th class="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider w-[20%]">
                  Actor
                </th>
                <th class="px-4 py-3 text-left text-xs font-medium text-muted uppercase tracking-wider w-[10%]">
                  Outcome
                </th>
              </tr>
            </thead>
            <tbody class="bg-primary divide-y divide-default">
              {#if logs.length === 0}
                <tr>
                  <td colspan="5" class="px-4 py-8 text-center text-muted">
                    No audit logs found. Your actions will appear here as you use the system.
                  </td>
                </tr>
              {:else}
                {#each logs as log}
                  <tr class="hover:bg-hover transition-colors">
                    <td class="px-4 py-3 text-sm text-default whitespace-nowrap">
                      {formatDate(log.timestamp)}
                    </td>
                    <td class="px-4 py-3 text-sm whitespace-nowrap">
                      <span class="inline-flex rounded-full bg-blue-100 dark:bg-blue-900 px-2 py-1 text-xs font-medium text-blue-800 dark:text-blue-200">
                        {log.action}
                      </span>
                    </td>
                    <td class="px-4 py-3 text-sm text-default">
                      <div class="line-clamp-2" title={log.description}>
                        {log.description}
                      </div>
                    </td>
                    <td class="px-4 py-3 text-sm text-muted truncate">
                      {log.metadata?.actor?.email || log.metadata?.actor?.name || "System"}
                    </td>
                    <td class="px-4 py-3 text-sm whitespace-nowrap">
                      {#if log.outcome === "success"}
                        <span class="inline-flex rounded-full bg-green-100 dark:bg-green-900 px-2 py-1 text-xs font-medium text-green-800 dark:text-green-200">
                          Success
                        </span>
                      {:else}
                        <span class="inline-flex rounded-full bg-red-100 dark:bg-red-900 px-2 py-1 text-xs font-medium text-red-800 dark:text-red-200">
                          Failure
                        </span>
                      {/if}
                    </td>
                  </tr>
                {/each}
              {/if}
            </tbody>
          </table>
        </div>
      </div>

      {#if totalPages > 1}
        <div class="mt-6 flex items-center justify-center space-x-2">
          <Button on:click={prevPage} disabled={page <= 1} variant="outlined" class="w-24">
            Previous
          </Button>
          <span class="text-default px-4 py-2 text-sm">
            Page {page} of {totalPages}
          </span>
          <Button on:click={nextPage} disabled={page >= totalPages} variant="outlined" class="w-24">
            Next
          </Button>
        </div>
      {/if}
    {/if}
  </Page.Main>
</Page.Root>
