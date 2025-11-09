<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { writable } from "svelte/store";
  import { Page } from "$lib/components/layout";
  import { Button, Input, Select } from "@intric/ui";
  import * as m from "$lib/paraglide/messages";
  import type { components } from "@intric/intric-js/types/schema";
  import type { UserSparse } from "@intric/intric-js";
  import type { CalendarDate } from "@internationalized/date";
  import { parseDate, today, getLocalTimeZone } from "@internationalized/date";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconCalendar } from "@intric/icons/calendar";
  import { IconXMark } from "@intric/icons/x-mark";
  import { IconDownload } from "@intric/icons/download";
  import { IconInfo } from "@intric/icons/info";
  import { slide } from "svelte/transition";
  import { getIntric } from "$lib/core/Intric";

  type AuditLogResponse = components["schemas"]["AuditLogResponse"];
  type ActionType = components["schemas"]["ActionType"];

  let { data } = $props();

  const intric = getIntric();

  // Expandable row state
  let expandedRows = $state<Set<string>>(new Set());

  // Filter states
  let dateRange = $state<{ start: CalendarDate | undefined; end: CalendarDate | undefined }>({
    start: undefined,
    end: undefined
  });
  let selectedAction = $state<ActionType | "all">("all");
  let selectedUser = $state<UserSparse | null>(null);
  let userSearchQuery = $state("");
  let userSearchResults = $state<UserSparse[]>([]);
  let isSearchingUsers = $state(false);
  let showUserDropdown = $state(false);
  let debounceTimer: ReturnType<typeof setTimeout>;
  let userSearchTimer: ReturnType<typeof setTimeout>;
  let isExporting = $state(false);

  // Action type options with better categorization
  const actionOptions: Array<{ value: ActionType | "all"; label: string; category?: string }> = [
    { value: "all", label: "All Actions" },
    { value: "user_created", label: "User Created", category: "admin" },
    { value: "user_updated", label: "User Updated", category: "admin" },
    { value: "user_deleted", label: "User Deleted", category: "admin" },
    { value: "role_modified", label: "Role Modified", category: "admin" },
    { value: "permission_changed", label: "Permission Changed", category: "admin" },
    { value: "tenant_settings_updated", label: "Tenant Settings Updated", category: "admin" },
    { value: "assistant_created", label: "Assistant Created", category: "user" },
    { value: "assistant_updated", label: "Assistant Updated", category: "user" },
    { value: "assistant_deleted", label: "Assistant Deleted", category: "user" },
    { value: "space_created", label: "Space Created", category: "user" },
    { value: "space_updated", label: "Space Updated", category: "user" },
    { value: "space_member_added", label: "Space Member Added", category: "user" },
    { value: "space_member_removed", label: "Space Member Removed", category: "user" },
    { value: "app_created", label: "App Created", category: "user" },
    { value: "app_updated", label: "App Updated", category: "user" },
    { value: "app_deleted", label: "App Deleted", category: "user" },
    { value: "app_executed", label: "App Executed", category: "user" },
    { value: "file_uploaded", label: "File Uploaded", category: "user" },
    { value: "file_deleted", label: "File Deleted", category: "user" },
    { value: "website_crawled", label: "Website Crawled", category: "system" },
  ];

  // Create store for Select component
  const actionStore = writable<{ value: ActionType | "all"; label: string }>({
    value: "all",
    label: "All Actions"
  });

  // Watch store changes
  $effect(() => {
    selectedAction = $actionStore.value;
  });

  // Initialize filters from URL on mount
  $effect(() => {
    const url = $page.url;
    const fromDate = url.searchParams.get("from_date");
    const toDate = url.searchParams.get("to_date");
    const action = url.searchParams.get("action");
    const actorId = url.searchParams.get("actor_id");

    // Set date range from URL
    if (fromDate && toDate) {
      try {
        dateRange = {
          start: parseDate(fromDate),
          end: parseDate(toDate)
        };
      } catch (e) {
        dateRange = { start: undefined, end: undefined };
      }
    } else {
      dateRange = { start: undefined, end: undefined };
    }

    // Set action from URL
    if (action && action !== "all") {
      selectedAction = action as ActionType;
      const option = actionOptions.find(opt => opt.value === action);
      if (option) {
        actionStore.set(option);
      }
    } else {
      selectedAction = "all";
      actionStore.set({ value: "all", label: "All Actions" });
    }

    // Set user from URL (if actor_id is present, we keep the selected user)
    // Note: We rely on user selecting from search, not parsing from URL
    if (!actorId) {
      selectedUser = null;
      userSearchQuery = "";
    }
  });

  // Date preset functions
  function setDatePreset(days: number) {
    const tz = getLocalTimeZone();
    const endDate = today(tz).add({ days: 1 }); // Add 1 day to include full current day
    const startDate = today(tz).subtract({ days: days - 1 }); // Subtract days-1 to get actual range
    dateRange = { start: startDate, end: endDate };
    applyFilters();
  }

  function formatTimestamp(timestamp: string): string {
    const date = new Date(timestamp);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 7) {
      return date.toLocaleDateString();
    } else if (days > 0) {
      return m.audit_days_ago({ count: days });
    } else if (hours > 0) {
      return m.audit_hours_ago({ count: hours });
    } else if (minutes > 0) {
      return m.audit_minutes_ago({ count: minutes });
    } else {
      return m.audit_just_now();
    }
  }

  function formatFullTimestamp(timestamp: string): string {
    return new Date(timestamp).toLocaleString();
  }

  function getActionBadgeClass(action: string): string {
    const adminActions = ["user_created", "user_updated", "user_deleted", "role_modified", "permission_changed", "tenant_settings_updated"];
    const systemActions = ["website_crawled"];

    if (adminActions.includes(action)) {
      return "bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300 border border-red-300 dark:border-red-700 font-medium";
    } else if (systemActions.includes(action)) {
      return "bg-gray-50 dark:bg-gray-900 text-gray-700 dark:text-gray-300 border border-gray-300 dark:border-gray-700 font-medium";
    } else {
      return "bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 border border-blue-300 dark:border-blue-700 font-medium";
    }
  }

  function toggleRowExpansion(logId: string) {
    if (expandedRows.has(logId)) {
      expandedRows.delete(logId);
    } else {
      expandedRows.add(logId);
    }
    expandedRows = new Set(expandedRows); // Trigger reactivity
  }

  function applyFilters() {
    const params = new URLSearchParams();

    if (data.page) params.set("page", data.page.toString());
    if (data.page_size) params.set("page_size", data.page_size.toString());

    if (dateRange?.start && dateRange?.end) {
      params.set("from_date", dateRange.start.toString());
      params.set("to_date", dateRange.end.toString());
    }

    if (selectedAction !== "all") {
      params.set("action", selectedAction);
    }

    if (selectedUser) {
      params.set("actor_id", selectedUser.id);
    }

    const url = params.toString() ? `/admin/audit-logs?${params.toString()}` : "/admin/audit-logs";
    goto(url, { noScroll: true, keepFocus: true });
  }

  function clearFilters() {
    dateRange = { start: undefined, end: undefined };
    selectedAction = "all";
    actionStore.set({ value: "all", label: "All Actions" });
    selectedUser = null;
    userSearchQuery = "";
    userSearchResults = [];
    goto("/admin/audit-logs", { noScroll: true });
  }

  // User search with debounce
  async function searchUsers(query: string) {
    userSearchQuery = query;

    if (query.length < 3) {
      userSearchResults = [];
      showUserDropdown = false;
      return;
    }

    clearTimeout(userSearchTimer);
    userSearchTimer = setTimeout(async () => {
      try {
        isSearchingUsers = true;
        const response = await intric.users.list({
          includeDetails: true,
          search_email: query,
          page: 1,
          page_size: 10,
        });
        userSearchResults = response.items || [];
        showUserDropdown = true;
      } catch (err) {
        console.error("User search failed:", err);
        userSearchResults = [];
      } finally {
        isSearchingUsers = false;
      }
    }, 300);
  }

  function selectUser(user: UserSparse) {
    selectedUser = user;
    userSearchQuery = user.email;
    userSearchResults = [];
    showUserDropdown = false;
    applyFilters();
  }

  function clearUserFilter() {
    selectedUser = null;
    userSearchQuery = "";
    userSearchResults = [];
    showUserDropdown = false;
    applyFilters();
  }

  function nextPage() {
    const params = new URLSearchParams($page.url.search);
    params.set("page", (data.page + 1).toString());
    goto(`/admin/audit-logs?${params.toString()}`, { noScroll: true });
  }

  function prevPage() {
    const params = new URLSearchParams($page.url.search);
    params.set("page", Math.max(1, data.page - 1).toString());
    goto(`/admin/audit-logs?${params.toString()}`, { noScroll: true });
  }

  async function exportToCSV() {
    try {
      isExporting = true;
      const params = new URLSearchParams($page.url.search);

      const response = await fetch(`/admin/audit-logs/export?${params.toString()}`, {
        method: "GET",
      });

      if (!response.ok) {
        throw new Error("Failed to export audit logs");
      }

      const blob = await response.blob();
      const dateStr = (dateRange?.start && dateRange?.end)
        ? `${dateRange.start.toString()}_to_${dateRange.end.toString()}`
        : new Date().toISOString().split('T')[0];
      const filename = `audit_logs_${dateStr}.csv`;

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
      alert("Failed to export audit logs. Please try again.");
    } finally {
      isExporting = false;
    }
  }

  // Auto-apply filters on action change
  $effect(() => {
    if (selectedAction !== undefined) {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        applyFilters();
      }, 300);
    }
  });

  // Auto-apply filters on date range change
  $effect(() => {
    if (dateRange?.start && dateRange?.end) {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        applyFilters();
      }, 300);
    }
  });

  // Count active filters
  let activeFilterCount = $derived(
    (dateRange?.start && dateRange?.end ? 1 : 0) +
    (selectedAction !== "all" ? 1 : 0) +
    (selectedUser ? 1 : 0)
  );
</script>

<svelte:head>
  <title>Eneo.ai – Admin – Audit Logs</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.audit_logs()}></Page.Title>
    <Button onclick={exportToCSV} variant="outlined" disabled={isExporting}>
      {#if isExporting}
        <div class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></div>
        {m.audit_exporting()}
      {:else}
        <IconDownload class="h-4 w-4" />
        {m.audit_export_csv()}
      {/if}
    </Button>
  </Page.Header>

  <Page.Main>
    <!-- Description -->
    <div class="mb-6">
      <p class="text-sm text-muted">
        {m.audit_logs_description()}
      </p>
    </div>

    <!-- Error State -->
    {#if data.error}
      <div class="mb-6 flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20">
        <IconInfo class="h-5 w-5 text-red-600 dark:text-red-400" />
        <p class="text-sm text-red-800 dark:text-red-200">{m.audit_error_loading()}</p>
        <Button onclick={() => window.location.reload()} variant="outlined" size="sm" class="ml-auto">
          {m.audit_retry()}
        </Button>
      </div>
    {/if}

    <!-- Filters Section -->
    <div class="mb-6 space-y-4 rounded-lg border border-default bg-subtle p-6">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-default">{m.audit_filters()}</h3>
        {#if activeFilterCount > 0}
          <button
            onclick={clearFilters}
            class="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-muted hover:bg-hover transition-colors"
          >
            <IconXMark class="h-3 w-3" />
            {m.audit_clear_filter({ count: activeFilterCount })}
          </button>
        {/if}
      </div>

      <!-- Date Presets -->
      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs font-medium text-muted">{m.audit_quick_range()}</span>
        <Button onclick={() => setDatePreset(7)} variant="outlined" size="sm">
          {m.audit_last_7_days()}
        </Button>
        <Button onclick={() => setDatePreset(30)} variant="outlined" size="sm">
          {m.audit_last_30_days()}
        </Button>
        <Button onclick={() => setDatePreset(90)} variant="outlined" size="sm">
          {m.audit_last_90_days()}
        </Button>
      </div>

      <!-- Filter Grid -->
      <div class="grid grid-cols-1 gap-4 md:grid-cols-3">
        <!-- Date Range Filter -->
        <div>
          <label class="mb-2 block text-xs font-medium text-default">{m.audit_date_range()}</label>
          <Input.DateRange bind:value={dateRange} class="w-full" />
        </div>

        <!-- Action Type Filter -->
        <div>
          <label class="mb-2 block text-xs font-medium text-default">{m.audit_action_type()}</label>
          <Select.Root customStore={actionStore}>
            <Select.Trigger class="w-full" placeholder="Select action type" />
            <Select.Options>
              {#each actionOptions as option}
                <Select.Item value={option.value} label={option.label} />
              {/each}
            </Select.Options>
          </Select.Root>
        </div>

        <!-- User Filter -->
        <div class="relative">
          <label class="mb-2 block text-xs font-medium text-default">{m.audit_user_filter()}</label>
          <div class="relative">
            <Input.Text
              bind:value={userSearchQuery}
              oninput={(e) => searchUsers(e.currentTarget.value)}
              onfocus={() => userSearchQuery.length >= 3 && userSearchResults.length > 0 && (showUserDropdown = true)}
              placeholder={m.audit_user_filter_placeholder()}
              class="w-full"
            />
            {#if selectedUser}
              <button
                onclick={clearUserFilter}
                class="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 hover:bg-hover transition-colors"
                aria-label="Clear user filter"
              >
                <IconXMark class="h-4 w-4 text-muted" />
              </button>
            {/if}
            {#if isSearchingUsers}
              <div class="absolute right-2 top-1/2 -translate-y-1/2">
                <div class="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent"></div>
              </div>
            {/if}
          </div>

          <!-- Dropdown Results -->
          {#if showUserDropdown && userSearchResults.length > 0}
            <div
              class="absolute z-10 mt-1 w-full rounded-md border border-default bg-default shadow-lg max-h-60 overflow-auto"
              transition:slide={{ duration: 150 }}
            >
              {#each userSearchResults as user}
                <button
                  onclick={() => selectUser(user)}
                  class="w-full px-3 py-2 text-left text-sm hover:bg-hover transition-colors flex flex-col gap-1"
                >
                  <span class="font-medium text-default">{user.email}</span>
                  {#if user.name}
                    <span class="text-xs text-muted">{user.name}</span>
                  {/if}
                </button>
              {/each}
            </div>
          {/if}
        </div>
      </div>

      <!-- Selected User Chip -->
      {#if selectedUser}
        <div class="flex items-center gap-2 mt-2">
          <div class="inline-flex items-center gap-2 rounded-full bg-blue-50 dark:bg-blue-950 px-3 py-1 text-sm">
            <span class="text-blue-700 dark:text-blue-300">
              {m.audit_filtering_by_user()}: <strong>{selectedUser.email}</strong>
            </span>
            <button
              onclick={clearUserFilter}
              class="rounded-full hover:bg-blue-100 dark:hover:bg-blue-900 p-0.5 transition-colors"
              aria-label="Clear user filter"
            >
              <IconXMark class="h-3 w-3 text-blue-700 dark:text-blue-300" />
            </button>
          </div>
        </div>
      {/if}
    </div>

    <!-- Results Summary -->
    <div class="mb-4 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <p class="text-sm text-muted">
          {m.audit_showing_results({ shown: data.logs.length, total: data.total_count })}
        </p>
        {#if data.total_pages > 1}
          <span class="text-sm text-muted">
            {m.audit_page_info({ current: data.page, total: data.total_pages })}
          </span>
        {/if}
      </div>

      {#if data.total_pages > 1}
        <div class="flex items-center gap-2">
          <Button onclick={prevPage} disabled={data.page <= 1} variant="outlined" size="sm">
            {m.audit_previous()}
          </Button>
          <Button onclick={nextPage} disabled={data.page >= data.total_pages} variant="outlined" size="sm">
            {m.audit_next()}
          </Button>
        </div>
      {/if}
    </div>

    <!-- Audit Logs Table -->
    <div class="rounded-lg border border-default shadow-sm">
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead class="sticky top-0 border-b border-default bg-subtle">
            <tr>
              <th class="w-8 px-4 py-3"></th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-default uppercase tracking-wider w-[12%]">
                {m.audit_timestamp()}
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-default uppercase tracking-wider w-[15%]">
                {m.audit_action()}
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-default uppercase tracking-wider w-[40%]">
                {m.audit_description()}
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-default uppercase tracking-wider w-[18%]">
                {m.audit_actor()}
              </th>
              <th class="px-4 py-3 text-left text-xs font-semibold text-default uppercase tracking-wider w-[10%]">
                {m.audit_entity()}
              </th>
              <th class="px-4 py-3 text-center text-xs font-semibold text-default uppercase tracking-wider w-[5%]">
                {m.audit_status()}
              </th>
            </tr>
          </thead>
          <tbody class="divide-y divide-default bg-primary">
            {#if data.logs.length === 0}
              <tr>
                <td colspan="7" class="px-4 py-16 text-center">
                  <div class="flex flex-col items-center gap-3">
                    <IconCalendar class="h-12 w-12 text-muted opacity-50" />
                    <div>
                      <p class="text-sm font-medium text-default">{m.audit_no_logs_found()}</p>
                      <p class="text-xs text-muted mt-1">
                        {activeFilterCount > 0 ? m.audit_try_adjusting_filters() : m.audit_logs_will_appear()}
                      </p>
                    </div>
                    {#if activeFilterCount > 0}
                      <Button onclick={clearFilters} variant="outlined" size="sm">
                        {m.audit_clear_filters()}
                      </Button>
                    {/if}
                  </div>
                </td>
              </tr>
            {:else}
              {#each data.logs as log, index (log.id || index)}
                {@const isExpanded = expandedRows.has(log.id || index.toString())}
                <!-- Main Row -->
                <tr
                  class="cursor-pointer transition-colors hover:bg-hover"
                  onclick={() => toggleRowExpansion(log.id || index.toString())}
                >
                  <td class="px-4 py-3">
                    {#if isExpanded}
                      <IconChevronDown class="h-4 w-4 text-muted rotate-180" />
                    {:else}
                      <IconChevronDown class="h-4 w-4 text-muted" />
                    {/if}
                  </td>
                  <td class="px-4 py-3">
                    <div class="flex flex-col">
                      <span class="text-sm font-medium text-default" title={formatFullTimestamp(log.timestamp)}>
                        {formatTimestamp(log.timestamp)}
                      </span>
                      <span class="text-xs text-muted">
                        {new Date(log.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  </td>
                  <td class="px-4 py-3">
                    <span class={`inline-flex rounded-md px-2.5 py-1 text-xs font-medium ${getActionBadgeClass(log.action)}`}>
                      {log.action.replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td class="px-4 py-3">
                    <p class="text-sm text-default line-clamp-2" title={log.description}>
                      {log.description}
                    </p>
                  </td>
                  <td class="px-4 py-3">
                    <div class="flex flex-col">
                      <span class="text-sm text-default truncate">
                        {log.metadata?.actor?.name || "System"}
                      </span>
                      {#if log.metadata?.actor?.email}
                        <span class="text-xs text-muted truncate">
                          {log.metadata.actor.email}
                        </span>
                      {/if}
                    </div>
                  </td>
                  <td class="px-4 py-3">
                    <span class="inline-flex rounded bg-gray-100 dark:bg-gray-800 px-2 py-1 text-xs font-medium text-gray-700 dark:text-gray-300">
                      {log.entity_type}
                    </span>
                  </td>
                  <td class="px-4 py-3 text-center">
                    {#if log.outcome === "success"}
                      <div class="inline-flex h-6 w-6 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30" title="Success">
                        <span class="text-green-600 dark:text-green-400 font-bold text-sm">✓</span>
                      </div>
                    {:else}
                      <div class="inline-flex h-6 w-6 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/30" title="Failure">
                        <span class="text-red-600 dark:text-red-400 font-bold text-sm">✗</span>
                      </div>
                    {/if}
                  </td>
                </tr>

                <!-- Expanded Metadata Row -->
                {#if isExpanded}
                  <tr transition:slide>
                    <td colspan="7" class="bg-subtle px-4 py-4">
                      <div class="mx-auto max-w-5xl space-y-3">
                        <h4 class="text-xs font-semibold text-default uppercase tracking-wider">{m.audit_full_details()}</h4>
                        <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                          <div class="rounded-lg border border-default bg-primary p-3">
                            <p class="text-xs font-medium text-muted mb-1">{m.audit_full_timestamp()}</p>
                            <p class="text-sm text-default">{formatFullTimestamp(log.timestamp)}</p>
                          </div>
                          <div class="rounded-lg border border-default bg-primary p-3">
                            <p class="text-xs font-medium text-muted mb-1">{m.audit_outcome()}</p>
                            <p class="text-sm text-default capitalize">{log.outcome}</p>
                          </div>
                        </div>
                        {#if log.metadata && Object.keys(log.metadata).length > 0}
                          <div class="rounded-lg border border-default bg-primary p-3">
                            <p class="text-xs font-medium text-muted mb-2">{m.audit_metadata_json()}</p>
                            <pre class="text-xs text-gray-800 dark:text-gray-200 rounded bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800 p-3 max-h-96 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(log.metadata, null, 2)}</pre>
                          </div>
                        {/if}
                      </div>
                    </td>
                  </tr>
                {/if}
              {/each}
            {/if}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Bottom Pagination -->
    {#if data.total_pages > 1}
      <div class="mt-6 flex items-center justify-center gap-3">
        <Button onclick={prevPage} disabled={data.page <= 1} variant="outlined" class="w-28">
          {m.audit_previous()}
        </Button>
        <span class="text-sm text-muted">
          {m.audit_page()} <span class="font-medium text-default">{data.page}</span> {m.audit_of()} <span class="font-medium text-default">{data.total_pages}</span>
        </span>
        <Button onclick={nextPage} disabled={data.page >= data.total_pages} variant="outlined" class="w-28">
          {m.audit_next()}
        </Button>
      </div>
    {/if}
  </Page.Main>
</Page.Root>
