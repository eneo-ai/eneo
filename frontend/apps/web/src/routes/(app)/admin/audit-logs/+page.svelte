<script lang="ts">
  import { goto, replaceState } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { page } from "$app/stores";
  import { writable } from "svelte/store";
  import { SvelteDate, SvelteSet, SvelteURLSearchParams } from "svelte/reactivity";
  import { Page } from "$lib/components/layout";
  import { Button, Input, Dropdown, ProgressBar } from "@intric/ui";
  import * as m from "$lib/paraglide/messages";
  import type { components, UserSparse } from "@intric/intric-js";
  import type { CalendarDate } from "@internationalized/date";
  import { parseDate, today, getLocalTimeZone } from "@internationalized/date";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconCalendar } from "@intric/icons/calendar";
  import { IconXMark } from "@intric/icons/x-mark";
  import { IconDownload } from "@intric/icons/download";
  import { IconInfo } from "@intric/icons/info";
  import { IconCopy } from "@intric/icons/copy";
  import { IconCheck } from "@intric/icons/check";
  import {
    CircleCheck,
    CircleX,
    Calendar,
    Shield,
    FileText,
    Settings,
    Trash2
  } from "lucide-svelte";
  import { fade, slide, scale } from "svelte/transition";
  import { onDestroy, untrack } from "svelte";
  import { getIntric } from "$lib/core/Intric";
  import { getLocale } from "$lib/paraglide/runtime";
  import AuditConfigTab from "./AuditConfigTab.svelte";
  import AccessJustificationForm from "./AccessJustificationForm.svelte";
  import { getActionLabel, getActionOptions } from "./audit-action-labels";

  type AuditLogResponse = components["schemas"]["AuditLogResponse"];
  type ActionType = components["schemas"]["ActionType"];

  let { data } = $props();

  const intric = getIntric();

  // Local state for audit logs (shadows data from load function to allow client-side updates)
  let logs = $state<AuditLogResponse[]>(untrack(() => data.logs || []));
  let totalCount = $state(untrack(() => data.total_count || 0));
  let currentPage = $state(untrack(() => data.page || 1));
  let pageSize = $state(untrack(() => data.page_size || 100));
  let totalPages = $state(untrack(() => data.total_pages || 0));
  let hasSessionState = $state(untrack(() => data.hasSession));
  let isFiltering = $state(false);

  // Track if we're using client-side filtering (to avoid $effect overwriting state)
  let useClientSideData = $state(false);

  // Abort controller for cancelling stale requests
  let filterAbortController: AbortController | null = null;

  // Only sync from load function data when NOT using client-side filtering
  // This prevents the effect from overwriting state during manual filtering
  $effect(() => {
    if (!useClientSideData) {
      logs = data.logs || [];
      totalCount = data.total_count || 0;
      currentPage = data.page || 1;
      pageSize = data.page_size || 100;
      totalPages = data.total_pages || 0;
      hasSessionState = data.hasSession;
    }
  });

  // Session state (determined by successful data load)
  let hasSession = $derived(hasSessionState);

  // Tab state
  let activeTab = $state<"logs" | "config">("logs");

  // Check URL for tab parameter
  $effect(() => {
    const tab = $page.url.searchParams.get("tab");
    if (tab === "config") {
      activeTab = "config";
    } else {
      activeTab = "logs";
    }
  });

  // Update URL when tab changes
  function switchTab(tab: "logs" | "config") {
    activeTab = tab;
    const params = new SvelteURLSearchParams($page.url.search);
    if (tab === "config") {
      params.set("tab", "config");
    } else {
      params.delete("tab");
    }
    const url = params.toString() ? `/admin/audit-logs?${params.toString()}` : "/admin/audit-logs";
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic query string built from URLSearchParams
    goto(url, { noScroll: true, keepFocus: true });
  }

  // Handle access justification submission
  async function handleJustificationSubmit(justification: {
    category: string;
    description: string;
  }) {
    try {
      // Create audit access session (sets HTTP-only cookie with session ID)
      await intric.audit.createAccessSession({
        category: justification.category,
        description: justification.description
      });

      // Reload page - session cookie is now set, grants access to audit logs
      await goto(resolve("/admin/audit-logs"), { invalidateAll: true });
    } catch (error) {
      console.error("Failed to create audit access session:", error);
      // Error will be shown by the form component
      throw error;
    }
  }

  // Expandable row state
  const expandedRows = new SvelteSet<string>();
  let copiedRowId = $state<string | null>(null);

  // Filter states
  let dateRange = $state<{ start: CalendarDate | undefined; end: CalendarDate | undefined }>({
    start: undefined,
    end: undefined
  });
  let selectedAction = $state<ActionType | "all">("all");
  let selectedActions = $state<ActionType[]>([]); // Multi-select support
  let showActionDropdown = $state(false); // For multi-select dropdown
  let actionSearchQuery = $state("");
  let selectedUser = $state<UserSparse | null>(null);
  let userSearchResults = $state<UserSparse[]>([]);
  let isSearchingUsers = $state(false);
  let showUserDropdown = $state(false);
  let userSearchCompleted = $state(false); // Track if search has completed (for empty state)

  // Unified scoped search state
  let searchScope = $state<"entity" | "user">("entity");
  let searchQuery = $state("");
  let showScopeDropdown = $state(false);
  let debounceTimer: ReturnType<typeof setTimeout> = undefined!;
  let userSearchTimer: ReturnType<typeof setTimeout> = undefined!;
  let entitySearchTimer: ReturnType<typeof setTimeout> = undefined!; // Debounce for entity search
  let isExporting = $state(false);
  let exportProgress = $state(0);
  let exportJobId = $state<string | null>(null);
  let exportStatus = $state<string | null>(null);
  let exportError = $state<string | null>(null);
  let exportProcessedRecords = $state(0);
  let exportTotalRecords = $state(0);
  let pollTimer: ReturnType<typeof setTimeout>;
  let _isInitializingFromUrl = false; // Flag to prevent auto-apply during URL initialization

  // Retention policy state - initialize from server data
  let retentionDays = $state<number>(untrack(() => data.retentionPolicy?.retention_days ?? 365));
  let isEditingRetention = $state(false);
  let retentionInputValue = $state<string>(
    untrack(() => String(data.retentionPolicy?.retention_days ?? 365))
  );
  let retentionInputNum = $derived(parseInt(retentionInputValue) || 0);
  let isSavingRetention = $state(false);
  let retentionError = $state<string | null>(null);

  // Track active quick filter preset (7, 30, 90 days, or null)
  let activePreset = $state<7 | 30 | 90 | null>(null);

  const actionOptions = $derived(getActionOptions());

  const filteredActionOptions = $derived(
    actionSearchQuery.length > 0
      ? actionOptions.filter(
          (o) =>
            o.value !== "all" && o.label.toLowerCase().includes(actionSearchQuery.toLowerCase())
        )
      : actionOptions.filter((o) => o.value !== "all")
  );

  // Create store for Select component
  const actionStore = writable<{ value: ActionType | "all"; label: string }>({
    value: "all",
    label: m.audit_all_actions()
  });

  $effect(() => {
    const newAction = $actionStore.value;
    if (selectedAction !== newAction) {
      selectedAction = newAction;
    }
  });

  $effect(() => {
    if (!showActionDropdown) {
      actionSearchQuery = "";
    }
  });

  // Initialize filters from URL on mount (skip when doing client-side filtering)
  $effect(() => {
    // Skip URL sync when using client-side filtering to prevent overwriting local state
    if (useClientSideData) return;

    const url = $page.url;
    const fromDate = url.searchParams.get("from_date");
    const toDate = url.searchParams.get("to_date");
    const action = url.searchParams.get("action");
    const actorId = url.searchParams.get("actor_id");
    const search = url.searchParams.get("search");

    // Set flag to prevent auto-apply effect from triggering during URL initialization
    _isInitializingFromUrl = true;

    // Set entity search from URL
    if (search) {
      searchScope = "entity";
      searchQuery = search;
    }

    // Set date range from URL
    if (fromDate && toDate) {
      try {
        // Subtract 1 day from end date when reading from URL
        // (We add 1 day in applyFilters to make it inclusive)
        const endDateFromUrl = parseDate(toDate).subtract({ days: 1 });
        dateRange = {
          start: parseDate(fromDate),
          end: endDateFromUrl
        };

        // Detect if the date range matches a preset
        activePreset = detectPresetFromDateRange(parseDate(fromDate), endDateFromUrl);
      } catch (e) {
        dateRange = { start: undefined, end: undefined };
        activePreset = null;
      }
    } else {
      dateRange = { start: undefined, end: undefined };
      activePreset = null;
    }

    // Set actions from URL (multi-select support)
    const actions = url.searchParams.get("actions");
    if (actions) {
      selectedActions = actions.split(",") as ActionType[];
      selectedAction = "all"; // Keep legacy state at default
    } else if (action && action !== "all") {
      // Legacy single-action support (backwards compatible)
      selectedAction = action as ActionType;
      selectedActions = [action as ActionType];
      const option = actionOptions.find((opt) => opt.value === action);
      if (option) {
        actionStore.set(option);
      }
    } else {
      selectedAction = "all";
      selectedActions = [];
      actionStore.set({ value: "all", label: m.audit_all_actions() });
    }

    // Set user from URL (if actor_id is present, we keep the selected user)
    // Note: We rely on user selecting from search, not parsing from URL
    // Only reset on actual page load to prevent race conditions when switching scopes
    if (!actorId) {
      selectedUser = null;
    }

    // Reset flag after the effect cycle completes
    queueMicrotask(() => {
      _isInitializingFromUrl = false;
    });
  });

  // Date preset functions (toggle behavior - click again to deselect)
  function setDatePreset(days: 7 | 30 | 90) {
    // Toggle off if clicking the same preset
    if (activePreset === days) {
      dateRange = { start: undefined, end: undefined };
      activePreset = null;
      return;
    }

    const tz = getLocalTimeZone();
    const endDate = today(tz); // Set to current day (applyFilters will add 1 day to make it inclusive)
    const startDate = today(tz).subtract({ days: days - 1 }); // Subtract days-1 to get actual range
    dateRange = { start: startDate, end: endDate };
    activePreset = days; // Track which preset is active
  }

  // Helper function to detect which preset matches a date range
  function detectPresetFromDateRange(
    start: CalendarDate | undefined,
    end: CalendarDate | undefined
  ): 7 | 30 | 90 | null {
    if (!start || !end) return null;

    const tz = getLocalTimeZone();
    const currentEnd = today(tz);

    // Check if end date matches today
    if (!end.compare(currentEnd)) {
      // Calculate days difference
      const daysDiff = currentEnd.toDate(tz).getTime() - start.toDate(tz).getTime();
      const days = Math.round(daysDiff / (1000 * 60 * 60 * 24)) + 1; // +1 to include both start and end

      // Check if it matches one of our presets
      if (days === 7) return 7;
      if (days === 30) return 30;
      if (days === 90) return 90;
    }

    return null;
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
      return date.toLocaleDateString(getLocale());
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
    return new Date(timestamp).toLocaleString(getLocale());
  }

  function formatJsonWithSyntaxHighlighting(obj: Record<string, unknown>): string {
    const json = JSON.stringify(obj, null, 2);
    return json
      .replace(/"([^"]+)":/g, '<span class="text-blue-600 dark:text-blue-400">"$1"</span>:') // Keys
      .replace(/: "([^"]*)"/g, ': <span class="text-green-600 dark:text-green-400">"$1"</span>') // String values
      .replace(/: (\d+)/g, ': <span class="text-orange-600 dark:text-orange-400">$1</span>') // Numbers
      .replace(
        /: (true|false|null)/g,
        ': <span class="text-purple-600 dark:text-purple-400">$1</span>'
      ); // Booleans/null
  }

  function getActionBadgeClass(action: string): string {
    // Admin/security actions (critical - needs attention) - RED
    const adminActions = [
      "user_created",
      "user_updated",
      "user_deleted",
      "role_modified",
      "permission_changed",
      "tenant_settings_updated"
    ];

    // System actions - GRAY
    const systemActions = ["website_crawled"];

    if (adminActions.includes(action)) {
      return "bg-red-50 dark:bg-red-950 text-red-900 dark:text-red-300 border border-red-300 dark:border-red-700 font-medium";
    } else if (systemActions.includes(action)) {
      return "bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-300 border border-gray-300 dark:border-gray-700 font-medium";
    } else {
      // All user content actions - BLUE (neutral, informational)
      return "bg-blue-50 dark:bg-blue-950 text-blue-900 dark:text-blue-300 border border-blue-300 dark:border-blue-700 font-medium";
    }
  }

  function toggleRowExpansion(logId: string) {
    if (expandedRows.has(logId)) {
      expandedRows.delete(logId);
    } else {
      expandedRows.add(logId);
    }
  }

  async function copyJsonToClipboard(json: Record<string, unknown>, logId: string) {
    try {
      await navigator.clipboard.writeText(JSON.stringify(json, null, 2));
      copiedRowId = logId;
      setTimeout(() => {
        copiedRowId = null;
      }, 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  }

  async function applyFilters() {
    // Mark that we're using client-side filtering (prevents $effect from overwriting state)
    useClientSideData = true;

    // Cancel any pending request to prevent race conditions
    if (filterAbortController) {
      filterAbortController.abort();
    }
    filterAbortController = new AbortController();

    const params = new SvelteURLSearchParams();

    // Build filter params for API call
    const filterParams: {
      page?: number;
      page_size?: number;
      from_date?: string;
      to_date?: string;
      actions?: string[];
      actor_id?: string;
      search?: string;
    } = {
      page: currentPage,
      page_size: pageSize
    };

    if (currentPage) params.set("page", currentPage.toString());
    if (pageSize) params.set("page_size", pageSize.toString());

    if (dateRange?.start && dateRange?.end) {
      params.set("from_date", dateRange.start.toString());
      // Add 1 day to end date to make it inclusive (include full selected day)
      const inclusiveEndDate = dateRange.end.add({ days: 1 });
      params.set("to_date", inclusiveEndDate.toString());
      filterParams.from_date = dateRange.start.toString();
      filterParams.to_date = inclusiveEndDate.toString();
    }

    // Multi-action filter support
    if (selectedActions.length > 0) {
      params.set("actions", selectedActions.join(","));
      filterParams.actions = selectedActions;
    }

    if (selectedUser) {
      params.set("actor_id", selectedUser.id);
      filterParams.actor_id = selectedUser.id;
    }

    if (searchScope === "entity" && searchQuery.length >= 3) {
      params.set("search", searchQuery);
      filterParams.search = searchQuery;
    }

    if (activeTab === "config") {
      params.set("tab", "config");
    }

    // Update URL without triggering navigation (preserves session)
    const url = params.toString() ? `/admin/audit-logs?${params.toString()}` : "/admin/audit-logs";
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic query string built from URLSearchParams
    replaceState(url, {});

    // Fetch data directly without triggering load function
    try {
      isFiltering = true;
      const response = await intric.audit.list(filterParams);
      logs = response.logs || [];
      totalCount = response.total_count || 0;
      currentPage = response.page || 1;
      totalPages = response.total_pages || 0;
    } catch (error: unknown) {
      // Ignore abort errors (request was cancelled by a newer request)
      if (error instanceof DOMException && error.name === "AbortError") return;

      // If 401, session expired - show justification form
      const apiError = error as { status?: number };
      if (apiError?.status === 401) {
        hasSessionState = false;
        useClientSideData = false; // Reset to allow load function to take over
      } else {
        console.error("Failed to fetch audit logs:", error);
      }
    } finally {
      isFiltering = false;
    }
  }

  function clearFilters() {
    // Stop any pending debounce timers to prevent race conditions
    // This prevents reactive effects from triggering navigation while we manually navigate
    clearTimeout(debounceTimer);
    clearTimeout(userSearchTimer);
    clearTimeout(entitySearchTimer);

    dateRange = { start: undefined, end: undefined };
    selectedAction = "all";
    selectedActions = []; // Clear multi-select
    actionStore.set({ value: "all", label: m.audit_all_actions() });
    selectedUser = null;
    searchQuery = "";
    searchScope = "entity";
    userSearchResults = [];
    showScopeDropdown = false;
    userSearchCompleted = false;
    activePreset = null; // Clear active preset

    // Refetch data with cleared filters (this also updates the URL)
    applyFilters();
  }

  // Unified scoped search handler
  function handleScopedSearch(query: string) {
    searchQuery = query;

    if (searchScope === "user") {
      // User search logic - reset completed flag on any query change
      userSearchCompleted = false;

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
            page_size: 10
          });
          userSearchResults = response?.items || [];
          showUserDropdown = userSearchResults.length > 0;
          userSearchCompleted = true; // Mark search as completed (for empty state)
        } catch (err) {
          console.error("User search failed:", err);
          userSearchResults = [];
          userSearchCompleted = true; // Still mark as completed even on error
        } finally {
          isSearchingUsers = false;
        }
      }, 300);
    }
  }

  function selectUser(user: UserSparse) {
    selectedUser = user;
    searchQuery = user.email;
    userSearchResults = [];
    showUserDropdown = false;
    userSearchCompleted = false; // Reset since user is now selected
  }

  function clearUserFilter() {
    selectedUser = null;
    if (searchScope === "user") {
      searchQuery = "";
    }
    userSearchResults = [];
    showUserDropdown = false;
    userSearchCompleted = false;
  }

  function clearSearch() {
    searchQuery = "";
    clearTimeout(entitySearchTimer);
    clearTimeout(userSearchTimer);
    userSearchResults = [];
    showUserDropdown = false;
    userSearchCompleted = false;
  }

  function toggleAction(actionValue: ActionType) {
    if (selectedActions.includes(actionValue)) {
      selectedActions = selectedActions.filter((a) => a !== actionValue);
    } else {
      selectedActions = [...selectedActions, actionValue];
    }
  }

  // Handle scope change - preserve query and re-trigger search in new scope
  function handleScopeChange(newScope: "entity" | "user") {
    // Clear ALL pending search timers to prevent race conditions
    clearTimeout(entitySearchTimer);
    clearTimeout(userSearchTimer);

    searchScope = newScope;
    showScopeDropdown = false;

    // Reset user-specific state when switching away from user scope
    if (newScope === "entity") {
      selectedUser = null;
      userSearchResults = [];
      showUserDropdown = false;
      userSearchCompleted = false;
    } else {
      // Switching to user scope - reset completed flag for fresh search
      userSearchCompleted = false;
    }

    // Preserve searchQuery and immediately trigger search in new scope
    if (searchQuery.length > 0) {
      handleScopedSearch(searchQuery);
    }
  }

  // Click outside handler for scope dropdown
  function handleClickOutside(event: MouseEvent) {
    const target = event.target as HTMLElement;
    if (showScopeDropdown && !target.closest(".scope-dropdown-container")) {
      showScopeDropdown = false;
    }
    if (showUserDropdown && !target.closest(".user-dropdown-container")) {
      showUserDropdown = false;
    }
  }

  function nextPage() {
    currentPage = currentPage + 1;
    applyFilters();
  }

  function prevPage() {
    currentPage = Math.max(1, currentPage - 1);
    applyFilters();
  }

  async function exportLogs(format: "csv" | "json") {
    try {
      isExporting = true;
      exportProgress = 0;
      exportStatus = "pending";
      exportError = null;
      exportProcessedRecords = 0;
      exportTotalRecords = 0;

      // Build export request body with current filters
      const params = $page.url.searchParams;
      const requestBody: Record<string, string> = {
        format: format === "json" ? "jsonl" : "csv"
      };

      // Add filter parameters
      const fromDate = params.get("from_date");
      if (fromDate) {
        requestBody.from_date = fromDate;
      }
      const toDate = params.get("to_date");
      if (toDate) {
        requestBody.to_date = toDate;
      }
      const actionParam = params.get("action");
      if (actionParam && actionParam !== "all") {
        requestBody.action = actionParam;
      }
      const actorId = params.get("actor_id");
      if (actorId) {
        requestBody.actor_id = actorId;
      }

      // 1. Request async export
      const response = await fetch("/admin/audit-logs/export/async", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(requestBody)
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to start export");
      }

      const { job_id } = await response.json();
      exportJobId = job_id;
      exportStatus = "pending";

      // 2. Poll for status
      await pollExportStatus(job_id, format);
    } catch (err) {
      console.error("Export failed:", err);
      exportError = err instanceof Error ? err.message : "Failed to export audit logs";
      exportStatus = "failed";
    }
  }

  async function pollExportStatus(jobId: string, format: "csv" | "json") {
    const poll = async () => {
      try {
        const statusResponse = await fetch(`/admin/audit-logs/export/${jobId}/status`);

        if (!statusResponse.ok) {
          throw new Error("Failed to get export status");
        }

        const status = await statusResponse.json();
        exportStatus = status.status;
        exportProgress = status.progress;
        exportProcessedRecords = status.processed_records;
        exportTotalRecords = status.total_records;

        if (status.status === "completed") {
          // 3. Trigger download
          clearTimeout(pollTimer);
          isExporting = false;

          // Build filename
          const dateStr =
            dateRange?.start && dateRange?.end
              ? `${dateRange.start.toString()}_to_${dateRange.end.toString()}`
              : new Date().toISOString().split("T")[0];
          const extension = format === "json" ? "jsonl" : "csv";
          const filename = `audit_logs_${dateStr}.${extension}`;

          // Create a hidden link and click it to download
          const a = document.createElement("a");
          a.href = `/admin/audit-logs/export/${jobId}/download`;
          a.download = filename;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);

          // Reset state after a short delay
          setTimeout(() => {
            resetExportState();
          }, 1000);
        } else if (status.status === "failed") {
          clearTimeout(pollTimer);
          exportError = status.error_message || "Export failed";
          isExporting = false;
        } else if (status.status === "cancelled") {
          clearTimeout(pollTimer);
          exportError = "Export was cancelled";
          isExporting = false;
        } else {
          // Continue polling (pending or processing)
          pollTimer = setTimeout(poll, 2000);
        }
      } catch (err) {
        console.error("Status poll failed:", err);
        clearTimeout(pollTimer);
        exportError = "Failed to check export status";
        exportStatus = "failed";
        isExporting = false;
      }
    };

    // Start polling
    poll();
  }

  async function cancelExport() {
    if (!exportJobId) return;

    try {
      const response = await fetch(`/admin/audit-logs/export/${exportJobId}/cancel`, {
        method: "POST"
      });

      if (response.ok) {
        clearTimeout(pollTimer);
        exportStatus = "cancelled";
        exportError = "Export cancelled by user";
        isExporting = false;
      }
    } catch (err) {
      console.error("Cancel failed:", err);
    }
  }

  function resetExportState() {
    exportProgress = 0;
    exportJobId = null;
    exportStatus = null;
    exportError = null;
    exportProcessedRecords = 0;
    exportTotalRecords = 0;
  }

  // Cleanup timers on component unmount to prevent navigation issues
  onDestroy(() => {
    clearTimeout(debounceTimer);
    clearTimeout(userSearchTimer);
    clearTimeout(entitySearchTimer);
    clearTimeout(pollTimer);
  });

  // Count active filters
  let activeFilterCount = $derived(
    (dateRange?.start && dateRange?.end ? 1 : 0) +
      selectedActions.length + // Count each selected action as a filter
      (selectedUser ? 1 : 0) +
      (searchScope === "entity" && searchQuery.length >= 3 ? 1 : 0)
  );

  // Retention policy functions
  async function saveRetentionPolicy() {
    try {
      isSavingRetention = true;
      retentionError = null;

      const retentionDaysNum = parseInt(retentionInputValue) || 0;
      if (retentionDaysNum < 1 || retentionDaysNum > 2555) {
        retentionError = "Retention period must be between 1 and 2555 days";
        return;
      }

      const updated = await intric.audit.updateRetentionPolicy({
        retention_days: retentionDaysNum
      });

      retentionDays = updated.retention_days;
      isEditingRetention = false;
    } catch (err) {
      console.error("Failed to save retention policy:", err);
      retentionError = "Failed to update retention policy. Please try again.";
    } finally {
      isSavingRetention = false;
    }
  }

  function cancelRetentionEdit() {
    retentionInputValue = String(retentionDays);
    isEditingRetention = false;
    retentionError = null;
  }

  // Calculate cutoff date for retention
  function getRetentionCutoffDate(days: number): string {
    const cutoff = new SvelteDate();
    cutoff.setDate(cutoff.getDate() - days);
    return cutoff.toLocaleDateString("sv-SE");
  }
</script>

<svelte:head>
  <title>Eneo.ai – Admin – Audit Logs</title>
</svelte:head>

<svelte:window onclick={handleClickOutside} />

<Page.Root>
  <Page.Header>
    <div class="flex items-center gap-4">
      <Page.Title title={m.audit_logs()}></Page.Title>
    </div>
    {#if activeTab === "logs" && hasSession}
      {#if isExporting}
        <!-- Export Progress UI -->
        <div class="flex items-center gap-3">
          <div class="flex min-w-[200px] flex-col gap-1">
            <div class="flex items-center justify-between text-xs">
              <span class="text-muted">
                {exportStatus === "pending" ? m.audit_export_preparing() : m.audit_exporting()}
              </span>
              <span class="text-default font-medium">{exportProgress}%</span>
            </div>
            <ProgressBar progress={exportProgress} />
            {#if exportTotalRecords > 0}
              <span class="text-muted text-xs">
                {exportProcessedRecords.toLocaleString()} / {exportTotalRecords.toLocaleString()}
                {m.audit_records()}
              </span>
            {/if}
          </div>
          <Button
            variant="simple"
            onclick={cancelExport}
            class="text-red-600 hover:bg-red-50 hover:text-red-700 dark:text-red-400 dark:hover:bg-red-950 dark:hover:text-red-300"
          >
            <IconXMark class="h-4 w-4" />
            {m.audit_cancel()}
          </Button>
        </div>
      {:else if exportError}
        <!-- Export Error UI -->
        <div class="flex items-center gap-3">
          <div
            class="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
          >
            <IconInfo class="h-4 w-4" />
            <span>{exportError}</span>
          </div>
          <Button variant="simple" onclick={resetExportState}>
            <IconXMark class="h-4 w-4" />
          </Button>
        </div>
      {:else}
        <!-- Normal Export Buttons -->
        <div class="flex gap-[1px]">
          <Button
            variant="primary"
            onclick={() => exportLogs("csv")}
            disabled={isExporting}
            class="!rounded-r-none"
          >
            <IconDownload class="h-4 w-4" />
            Export ({totalCount})
          </Button>
          <Dropdown.Root gutter={2} arrowSize={0} placement="bottom-end">
            <Dropdown.Trigger asFragment let:trigger>
              <Button
                padding="icon"
                variant="primary"
                is={trigger}
                disabled={isExporting}
                class="!rounded-l-none"
              >
                <IconChevronDown></IconChevronDown>
              </Button>
            </Dropdown.Trigger>
            <Dropdown.Menu let:item>
              <Button is={item} onclick={() => exportLogs("csv")}>
                <IconDownload size="sm"></IconDownload>
                Download as CSV
              </Button>
              <Button is={item} onclick={() => exportLogs("json")}>
                <IconDownload size="sm"></IconDownload>
                Download as JSON
              </Button>
            </Dropdown.Menu>
          </Dropdown.Root>
        </div>
      {/if}
    {/if}
  </Page.Header>

  <Page.Main>
    {#if !(activeTab === "logs" && !hasSession)}
      <!-- Description with better spacing and visual treatment -->
      <div class="mb-6 px-4 pt-4 sm:px-6 lg:px-8">
        <p class="text-muted text-sm leading-relaxed">
          {m.audit_logs_description()}
        </p>
      </div>

      <!-- Tabs with improved styling -->
      <div class="mb-6 px-4 sm:px-6 lg:px-8">
        <div class="bg-subtle border-default inline-flex gap-1 rounded-lg border p-1.5 shadow-sm">
          <button
            onclick={() => switchTab("logs")}
            class={`flex items-center justify-center gap-2 rounded-md px-6 py-2.5 text-sm font-semibold transition-all duration-150 ${
              activeTab === "logs"
                ? "bg-accent-default text-on-fill ring-accent-default/20 shadow-accent-default/25 shadow-md ring-1"
                : "text-muted hover:text-default hover:bg-hover hover:scale-[1.02] active:scale-[0.98]"
            }`}
          >
            <FileText class="h-4 w-4" />
            {m.audit_tab_logs()}
          </button>
          <button
            onclick={() => switchTab("config")}
            class={`flex items-center justify-center gap-2 rounded-md px-6 py-2.5 text-sm font-semibold transition-all duration-150 ${
              activeTab === "config"
                ? "bg-accent-default text-on-fill ring-accent-default/20 shadow-accent-default/25 shadow-md ring-1"
                : "text-muted hover:text-default hover:bg-hover hover:scale-[1.02] active:scale-[0.98]"
            }`}
          >
            <Settings class="h-4 w-4" />
            {m.audit_tab_config()}
          </button>
        </div>
      </div>
    {/if}

    {#if activeTab === "logs"}
      <!-- Logs Tab Content -->
      {#if !hasSession}
        <!-- Access Justification Form -->
        <AccessJustificationForm onSubmit={handleJustificationSubmit} />
      {:else}
        <div class="px-4 pb-8 sm:px-6 lg:px-8">
          <!-- Retention Policy Section -->
          <div
            class="border-default bg-subtle mb-8 rounded-xl border p-5 transition-shadow duration-200 hover:shadow-md"
          >
            <div class="mb-3 flex items-center justify-between">
              <div class="flex items-center gap-2.5">
                <div class="bg-accent/10 rounded-lg p-1.5">
                  <Shield class="text-accent h-5 w-5" />
                </div>
                <div>
                  <h3 class="text-default text-sm font-semibold">{m.audit_retention_policy()}</h3>
                  <p class="text-muted mt-0.5 text-xs">
                    Automatisk borttagning av gamla granskningsloggar
                  </p>
                </div>
              </div>
              {#if !isEditingRetention}
                <Button
                  onclick={() => (isEditingRetention = true)}
                  variant="simple"
                  size="sm"
                  class="min-w-[80px]"
                >
                  {m.audit_retention_edit()}
                </Button>
              {/if}
            </div>

            {#if !isEditingRetention}
              <!-- Display Mode -->
              <div class="bg-primary space-y-2 rounded-lg p-4" transition:slide={{ duration: 200 }}>
                <div class="flex items-start gap-3">
                  <div class="bg-accent/10 rounded-md p-1.5">
                    <Calendar class="text-accent h-4 w-4" />
                  </div>
                  <div class="flex-1">
                    <div class="mb-1 flex items-baseline gap-2">
                      <span class="text-default text-lg font-semibold">{retentionDays}</span>
                      <span class="text-muted text-xs">
                        {retentionDays === 1 ? "dag" : "dagar"}
                        {retentionDays === 365
                          ? ` (1 ${m.audit_retention_year()})`
                          : retentionDays === 730
                            ? ` (2 ${m.audit_retention_years()})`
                            : retentionDays === 90
                              ? ` (3 ${m.audit_retention_months()})`
                              : retentionDays === 2555
                                ? ` (7 ${m.audit_retention_years()})`
                                : ""}
                      </span>
                    </div>
                    <p class="text-muted text-xs leading-relaxed">
                      {m.audit_retention_cutoff({ date: getRetentionCutoffDate(retentionDays) })}
                    </p>
                  </div>
                </div>
              </div>
            {:else}
              <!-- Edit Mode -->
              <div class="space-y-3" transition:slide={{ duration: 200 }}>
                <div class="bg-primary space-y-3 rounded-lg p-4">
                  <div class="max-w-xl">
                    <!-- svelte-ignore a11y_label_has_associated_control -->
                    <label class="text-default mb-2 block text-xs font-semibold"
                      >{m.audit_retention_period_label()}</label
                    >
                    <div class="mb-4 flex flex-col items-start gap-2 sm:flex-row sm:items-center">
                      <div class="flex items-center gap-2">
                        <!-- @ts-ignore Input.Text type="number" binding -->
                        <Input.Text
                          bind:value={retentionInputValue}
                          type="number"
                          min="1"
                          max="2555"
                          class="w-20"
                          inputClass="text-center text-sm font-medium"
                        />
                        <span class="text-muted text-xs">
                          {m.audit_retention_days_unit()}
                        </span>
                      </div>
                      <div class="text-muted text-xs">
                        {retentionInputNum === 365
                          ? `(1 ${m.audit_retention_year()})`
                          : retentionInputNum === 730
                            ? `(2 ${m.audit_retention_years()})`
                            : retentionInputNum === 90
                              ? `(3 ${m.audit_retention_months()})`
                              : retentionInputNum === 2555
                                ? `(7 ${m.audit_retention_years()})`
                                : ""}
                      </div>
                    </div>
                    <div class="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                      <Button
                        onclick={() => (retentionInputValue = "90")}
                        variant={retentionInputNum === 90 ? "primary" : "simple"}
                        size="sm"
                        class="w-full text-sm font-medium"
                      >
                        3 mån
                      </Button>
                      <Button
                        onclick={() => (retentionInputValue = "365")}
                        variant={retentionInputNum === 365 ? "primary" : "simple"}
                        size="sm"
                        class="w-full text-sm font-medium"
                      >
                        1 år
                      </Button>
                      <Button
                        onclick={() => (retentionInputValue = "730")}
                        variant={retentionInputNum === 730 ? "primary" : "simple"}
                        size="sm"
                        class="w-full text-sm font-medium"
                      >
                        2 år
                      </Button>
                      <Button
                        onclick={() => (retentionInputValue = "2555")}
                        variant={retentionInputNum === 2555 ? "primary" : "simple"}
                        size="sm"
                        class="w-full text-sm font-medium"
                      >
                        7 år
                      </Button>
                    </div>
                  </div>
                </div>

                {#if retentionInputNum !== retentionDays}
                  <div
                    class={`rounded-lg border-l-4 p-2.5 text-xs transition-all ${
                      retentionInputNum < retentionDays
                        ? "border border-red-200 border-l-red-500 bg-red-50 dark:border-red-800 dark:bg-red-950/50"
                        : "border border-blue-200 border-l-blue-500 bg-blue-50 dark:border-blue-800 dark:bg-blue-950/50"
                    }`}
                  >
                    {#if retentionInputNum < retentionDays}
                      <div class="flex items-start gap-2.5">
                        <div class="rounded-full bg-red-100 p-1.5 dark:bg-red-900">
                          <IconInfo class="h-4 w-4 text-red-600 dark:text-red-400" />
                        </div>
                        <div class="flex-1 space-y-1">
                          <p class="text-xs font-semibold text-red-900 dark:text-red-200">
                            {m.audit_retention_warning_title()}
                          </p>
                          <p class="text-xs leading-[1.4] text-red-800 dark:text-red-300">
                            {m.audit_retention_warning_desc({
                              date: getRetentionCutoffDate(retentionInputNum)
                            })}
                          </p>
                        </div>
                      </div>
                    {:else}
                      <div class="flex items-start gap-2.5">
                        <div class="rounded-full bg-blue-100 p-1.5 dark:bg-blue-900">
                          <IconInfo class="h-4 w-4 text-blue-600 dark:text-blue-400" />
                        </div>
                        <div class="flex-1 space-y-1">
                          <p class="text-xs font-semibold text-blue-900 dark:text-blue-200">
                            {m.audit_retention_info_title()}
                          </p>
                          <p class="text-xs leading-[1.4] text-blue-800 dark:text-blue-300">
                            {m.audit_retention_info_desc()}
                          </p>
                        </div>
                      </div>
                    {/if}
                  </div>
                {/if}

                {#if retentionError}
                  <div class="text-xs text-red-600 dark:text-red-400">
                    {retentionError}
                  </div>
                {/if}

                <div class="border-default mt-3 border-t pt-3">
                  <p class="text-muted mb-2 text-xs">
                    {m.audit_retention_range()}
                  </p>
                  <div class="flex items-center justify-end gap-2">
                    <Button
                      onclick={cancelRetentionEdit}
                      variant="simple"
                      disabled={isSavingRetention}
                      class="min-w-[80px] text-sm font-medium"
                    >
                      {m.audit_retention_cancel()}
                    </Button>
                    <Button
                      onclick={saveRetentionPolicy}
                      variant="primary"
                      disabled={isSavingRetention || retentionInputNum === retentionDays}
                      class="min-w-[120px] text-sm font-medium"
                    >
                      {#if isSavingRetention}
                        <div class="flex items-center gap-2">
                          <div
                            class="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"
                          ></div>
                          {m.audit_retention_saving()}
                        </div>
                      {:else}
                        {m.audit_retention_save()}
                      {/if}
                    </Button>
                  </div>
                </div>
              </div>
            {/if}
          </div>

          <!-- Error State -->
          {#if data.error}
            <div
              class="mb-6 flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20"
            >
              <IconInfo class="h-5 w-5 text-red-600 dark:text-red-400" />
              <p class="text-sm text-red-800 dark:text-red-200">{m.audit_error_loading()}</p>
              <Button
                onclick={() => window.location.reload()}
                variant="outlined"
                size="sm"
                class="ml-auto"
              >
                {m.audit_retry()}
              </Button>
            </div>
          {/if}

          <!-- Filter Toolbar -->
          <div class="border-default bg-subtle mb-4 rounded-lg border p-4">
            <div class="flex flex-wrap items-center gap-3">
              <!-- Scoped Search (first, fills available space) -->
              <div
                class="scope-dropdown-container user-dropdown-container relative min-w-[280px] flex-1"
              >
                <!-- Scope trigger (inside input, left side) -->
                <div class="absolute top-1/2 left-2 z-10 flex -translate-y-1/2 items-center">
                  <button
                    onclick={() => (showScopeDropdown = !showScopeDropdown)}
                    aria-haspopup="listbox"
                    aria-expanded={showScopeDropdown}
                    aria-label="Search scope: {searchScope === 'entity' ? 'Entity' : 'User'}"
                    class="text-muted bg-subtle/80 border-default/40 hover:bg-hover hover:text-default hover:border-default/60 focus-visible:ring-accent-default flex h-7 items-center
                    gap-1.5 rounded-md border px-2.5
                    text-xs font-semibold transition-all
                    duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1"
                  >
                    {searchScope === "entity"
                      ? m.audit_search_scope_entity()
                      : m.audit_search_scope_user()}
                    <IconChevronDown
                      class={`h-3 w-3 transition-transform duration-150 ${showScopeDropdown ? "rotate-180" : ""}`}
                    />
                  </button>

                  <!-- Scope Dropdown menu -->
                  {#if showScopeDropdown}
                    <div
                      role="listbox"
                      aria-label="Select search scope"
                      class="bg-primary border-default absolute top-full left-0 z-30 mt-1.5 min-w-[140px] overflow-hidden rounded-lg border py-1 shadow-lg"
                      transition:slide={{ duration: 150 }}
                    >
                      <button
                        role="option"
                        aria-selected={searchScope === "entity"}
                        onclick={() => handleScopeChange("entity")}
                        class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm transition-colors
                        {searchScope === 'entity'
                          ? 'text-accent-default bg-accent-default/5 font-medium'
                          : 'text-default hover:bg-subtle'}"
                      >
                        {m.audit_search_scope_entity()}
                        {#if searchScope === "entity"}
                          <IconCheck class="text-accent-default h-4 w-4" />
                        {/if}
                      </button>
                      <button
                        role="option"
                        aria-selected={searchScope === "user"}
                        onclick={() => handleScopeChange("user")}
                        class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm transition-colors
                        {searchScope === 'user'
                          ? 'text-accent-default bg-accent-default/5 font-medium'
                          : 'text-default hover:bg-subtle'}"
                      >
                        {m.audit_search_scope_user()}
                        {#if searchScope === "user"}
                          <IconCheck class="text-accent-default h-4 w-4" />
                        {/if}
                      </button>
                    </div>
                  {/if}

                  <!-- Visual divider -->
                  <div class="bg-default/40 ml-2 h-6 w-px"></div>
                </div>

                <!-- Search input -->
                <input
                  type="text"
                  bind:value={searchQuery}
                  oninput={(e) => handleScopedSearch(e.currentTarget.value)}
                  onfocus={() =>
                    searchScope === "user" &&
                    searchQuery.length >= 3 &&
                    userSearchResults.length > 0 &&
                    (showUserDropdown = true)}
                  placeholder={searchScope === "entity"
                    ? m.audit_search_placeholder_entity()
                    : m.audit_search_placeholder_user()}
                  aria-label={searchScope === "entity"
                    ? "Search by entity name"
                    : "Search by user email"}
                  autocomplete="off"
                  class="border-default bg-primary text-default placeholder:text-muted focus:ring-accent-default/30 focus:border-accent-default h-11 w-full rounded-lg border pr-10
                  pl-32 text-sm transition-all duration-150 focus:ring-2 focus:outline-none"
                />

                <!-- Clear button (right side) -->
                {#if searchQuery.length > 0}
                  <button
                    onclick={clearSearch}
                    class="text-muted hover:text-default hover:bg-hover focus-visible:ring-accent-default absolute top-1/2 right-2 -translate-y-1/2
                    rounded-md p-1.5 transition-all
                    duration-150 focus:outline-none focus-visible:ring-2"
                    aria-label={m.audit_search_clear()}
                  >
                    <IconXMark class="h-4 w-4" />
                  </button>
                {/if}

                <!-- Loading spinner for user search -->
                {#if isSearchingUsers && searchScope === "user"}
                  <div class="absolute top-1/2 right-8 -translate-y-1/2">
                    <div
                      class="border-accent-default h-4 w-4 animate-spin rounded-full border-2 border-t-transparent"
                    ></div>
                  </div>
                {/if}

                <!-- User dropdown results (only when scope = 'user') -->
                {#if searchScope === "user" && showUserDropdown && userSearchResults.length > 0}
                  <div
                    role="listbox"
                    aria-label="User search results"
                    class="border-default bg-primary absolute top-full right-0 left-0 z-20 mt-2 max-h-64 overflow-y-auto rounded-lg border shadow-xl"
                    transition:slide={{ duration: 150 }}
                  >
                    {#each userSearchResults as user, index (user.id || index)}
                      <button
                        role="option"
                        aria-selected={false}
                        onclick={() => selectUser(user)}
                        class="hover:bg-accent-default/5 focus:bg-accent-default/5 w-full px-4 py-3 text-left
                        transition-colors focus:outline-none
                        {index > 0 ? 'border-default/50 border-t' : ''}"
                      >
                        <div class="flex items-center gap-3">
                          <div
                            class="bg-accent-default/10 text-accent-default flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold"
                          >
                            {user.email.charAt(0).toUpperCase()}
                          </div>
                          <span class="text-default text-sm font-medium">{user.email}</span>
                        </div>
                      </button>
                    {/each}
                  </div>
                {/if}

                <!-- Empty state for user search (only shows after search completes with 0 results) -->
                {#if searchScope === "user" && searchQuery.length >= 3 && userSearchCompleted && userSearchResults.length === 0}
                  <div
                    class="border-default bg-primary absolute top-full right-0 left-0 z-20 mt-2 rounded-lg border p-4 shadow-lg"
                    transition:fade={{ duration: 150 }}
                  >
                    <div class="flex flex-col items-center gap-2 py-2 text-center">
                      <div class="bg-muted/20 rounded-full p-2">
                        <IconXMark class="text-muted h-5 w-5" />
                      </div>
                      <p class="text-muted text-sm">Inga användare hittades</p>
                      <p class="text-muted/70 text-xs">Försök med en annan sökning</p>
                    </div>
                  </div>
                {/if}
              </div>

              <!-- Filters Row (second) -->
              <div class="flex flex-wrap items-center gap-2 sm:gap-3 lg:gap-4">
                <Input.DateRange bind:value={dateRange} />

                <!-- Quick filter buttons (connected button group) -->
                <div
                  class="border-default/60 bg-subtle/50 flex h-10 flex-shrink-0 items-center overflow-hidden rounded-lg border"
                  role="group"
                  aria-label="Quick date presets"
                >
                  <button
                    onclick={() => setDatePreset(7)}
                    aria-pressed={activePreset === 7}
                    class={`focus-visible:ring-accent-default px-4 py-2 text-xs font-semibold transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset ${
                      activePreset === 7
                        ? "bg-accent-default text-white shadow-sm"
                        : "text-muted hover:bg-hover hover:text-default active:scale-95"
                    }`}
                  >
                    7d
                  </button>
                  <button
                    onclick={() => setDatePreset(30)}
                    aria-pressed={activePreset === 30}
                    class={`border-default/40 focus-visible:ring-accent-default border-x px-4 py-2 text-xs font-semibold transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset ${
                      activePreset === 30
                        ? "bg-accent-default border-x-transparent text-white shadow-sm"
                        : "text-muted hover:bg-hover hover:text-default active:scale-95"
                    }`}
                  >
                    30d
                  </button>
                  <button
                    onclick={() => setDatePreset(90)}
                    aria-pressed={activePreset === 90}
                    class={`focus-visible:ring-accent-default px-4 py-2 text-xs font-semibold transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset ${
                      activePreset === 90
                        ? "bg-accent-default text-white shadow-sm"
                        : "text-muted hover:bg-hover hover:text-default active:scale-95"
                    }`}
                  >
                    90d
                  </button>
                </div>

                <!-- Action Multi-Select -->
                <div class="relative min-w-[200px] sm:min-w-[220px]">
                  <Dropdown.Root
                    {...{ open: showActionDropdown }}
                    gutter={4}
                    placement="bottom-start"
                  >
                    <Dropdown.Trigger asFragment let:trigger>
                      <Button
                        is={trigger}
                        variant="outlined"
                        class="w-full justify-between"
                        aria-haspopup="listbox"
                        aria-expanded={showActionDropdown}
                        aria-label={selectedActions.length === 0
                          ? m.audit_all_actions()
                          : `${selectedActions.length} ${m.audit_actions_selected()}`}
                      >
                        <span class={selectedActions.length === 0 ? "text-muted" : "text-default"}>
                          {#if selectedActions.length === 0}
                            {m.audit_all_actions()}
                          {:else if selectedActions.length === 1}
                            {actionOptions.find((o) => o.value === selectedActions[0])?.label}
                          {:else}
                            {selectedActions.length} {m.audit_actions_selected()}
                          {/if}
                        </span>
                        <IconChevronDown
                          class={`text-muted h-4 w-4 transition-transform duration-200 ${showActionDropdown ? "rotate-180" : ""}`}
                        />
                      </Button>
                    </Dropdown.Trigger>
                    <Dropdown.Menu>
                      <!-- Container with search and scrollable list -->
                      <div class="-mx-2 -mb-2 min-w-[280px] sm:min-w-[300px]">
                        <!-- Search input (sticky at top) -->
                        <div class="bg-primary border-default sticky top-0 z-30 -mt-2 border-b p-2">
                          <input
                            type="text"
                            bind:value={actionSearchQuery}
                            placeholder="Sök åtgärder..."
                            class="border-default bg-subtle text-default placeholder:text-muted focus:ring-accent-default/30 focus:border-accent-default h-8 w-full rounded-md border
                            px-3 text-sm transition-all duration-150 focus:ring-2 focus:outline-none"
                            onclick={(e) => e.stopPropagation()}
                          />
                        </div>

                        <!-- Selected count header when items are selected -->
                        {#if selectedActions.length > 0}
                          <div
                            class="bg-primary border-default sticky top-10 z-20 flex items-center justify-between border-b px-3 py-2 text-xs font-medium shadow-sm"
                          >
                            <span class="text-muted"
                              >{selectedActions.length} {m.audit_actions_selected()}</span
                            >
                            <button
                              class="text-accent-default hover:bg-accent-default focus-visible:ring-accent-default rounded px-2 py-1 transition-all duration-150 hover:text-white focus:outline-none focus-visible:ring-2"
                              onclick={() => {
                                selectedActions = [];
                              }}
                              aria-label="Clear all selected actions"
                            >
                              {m.audit_clear_all()}
                            </button>
                          </div>
                        {/if}

                        <!-- Scrollable list -->
                        <div
                          class="relative max-h-[40vh] overflow-y-auto overscroll-contain scroll-smooth sm:max-h-[250px]"
                          role="listbox"
                          aria-multiselectable="true"
                          aria-label={m.audit_all_actions()}
                        >
                          <!-- Items list -->
                          {#if filteredActionOptions.length === 0}
                            <div class="text-muted px-3 py-4 text-center text-sm">
                              Inga åtgärder hittades
                            </div>
                          {:else}
                            {#each filteredActionOptions as option (option.value)}
                              {@const isSelected = selectedActions.includes(
                                option.value as ActionType
                              )}
                              <button
                                role="option"
                                aria-selected={isSelected}
                                tabindex={showActionDropdown ? 0 : -1}
                                class={`bg-primary hover:bg-hover focus:bg-hover focus-visible:ring-accent-default/50 flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm
                              transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset sm:py-2
                              ${isSelected ? "bg-accent-default/5" : ""}`}
                                onclick={() => toggleAction(option.value as ActionType)}
                                onkeydown={(e) => {
                                  if (e.key === "Enter" || e.key === " ") {
                                    e.preventDefault();
                                    toggleAction(option.value as ActionType);
                                  }
                                }}
                              >
                                <span
                                  class={`flex h-5 w-5 shrink-0 items-center justify-center rounded border-2 transition-all duration-200 sm:h-4 sm:w-4 ${
                                    isSelected
                                      ? "bg-accent-default border-accent-default shadow-accent-default/25 scale-100 shadow-sm"
                                      : "border-default/60 hover:border-default scale-95 hover:scale-100"
                                  }`}
                                  aria-hidden="true"
                                >
                                  {#if isSelected}
                                    <IconCheck class="text-on-fill h-3 w-3" />
                                  {/if}
                                </span>
                                <span
                                  class={`flex-1 ${isSelected ? "text-default font-medium" : "text-default"}`}
                                >
                                  {option.label}
                                </span>
                                {#if isSelected}
                                  <span class="sr-only">(selected)</span>
                                {/if}
                              </button>
                            {/each}
                          {/if}

                          <!-- Scroll fade indicator at bottom -->
                          <div
                            class="from-primary pointer-events-none sticky bottom-0 z-10 h-4 bg-gradient-to-t to-transparent"
                            aria-hidden="true"
                          ></div>
                        </div>
                      </div>
                    </Dropdown.Menu>
                  </Dropdown.Root>
                </div>

                <!-- Apply Filters Button -->
                <Button
                  variant="primary"
                  onclick={() => applyFilters()}
                  disabled={isFiltering}
                  class="min-w-[100px]"
                >
                  {#if isFiltering}
                    <div class="flex items-center gap-2">
                      <div
                        class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
                      ></div>
                      Tillämpar...
                    </div>
                  {:else}
                    Tillämpa
                  {/if}
                </Button>
              </div>
            </div>
          </div>

          <!-- Active Filter Chips (OUTSIDE toolbar) -->
          {#if activeFilterCount > 0}
            <div class="mb-4 flex flex-wrap items-center gap-2">
              {#if dateRange?.start && dateRange?.end && !activePreset}
                <span
                  transition:scale={{ duration: 150, start: 0.9 }}
                  class="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1 text-xs shadow-sm dark:bg-blue-950"
                >
                  <span class="text-blue-800 dark:text-blue-300">
                    {dateRange.start.toString()} – {dateRange.end.toString()}
                  </span>
                  <button
                    onclick={() => {
                      dateRange = { start: undefined, end: undefined };
                      activePreset = null;
                    }}
                    class="rounded-full p-0.5 transition-all duration-150 hover:scale-110 hover:bg-blue-100 dark:hover:bg-blue-900"
                  >
                    <IconXMark class="h-3 w-3 text-blue-700 dark:text-blue-300" />
                  </button>
                </span>
              {/if}

              {#each selectedActions as action (action)}
                <span
                  transition:scale={{ duration: 150, start: 0.9 }}
                  class="inline-flex items-center gap-1.5 rounded-full bg-purple-50 px-3 py-1 text-xs shadow-sm dark:bg-purple-950"
                >
                  <span class="text-purple-800 dark:text-purple-300">
                    {actionOptions.find((o) => o.value === action)?.label}
                  </span>
                  <button
                    onclick={() => {
                      selectedActions = selectedActions.filter((a) => a !== action);
                    }}
                    class="rounded-full p-0.5 transition-all duration-150 hover:scale-110 hover:bg-purple-100 dark:hover:bg-purple-900"
                  >
                    <IconXMark class="h-3 w-3 text-purple-700 dark:text-purple-300" />
                  </button>
                </span>
              {/each}

              {#if selectedUser}
                <span
                  transition:scale={{ duration: 150, start: 0.9 }}
                  class="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-3 py-1 text-xs shadow-sm dark:bg-green-950"
                >
                  <span class="text-green-800 dark:text-green-300">
                    {m.audit_filtering_by_user()}: {selectedUser.email}
                  </span>
                  <button
                    onclick={clearUserFilter}
                    class="rounded-full p-0.5 transition-all duration-150 hover:scale-110 hover:bg-green-100 dark:hover:bg-green-900"
                  >
                    <IconXMark class="h-3 w-3 text-green-700 dark:text-green-300" />
                  </button>
                </span>
              {/if}

              {#if searchScope === "entity" && searchQuery.length >= 3}
                <span
                  transition:scale={{ duration: 150, start: 0.9 }}
                  class="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-3 py-1 text-xs shadow-sm dark:bg-amber-950"
                >
                  <span class="text-amber-800 dark:text-amber-300">
                    {m.audit_filtering_by_entity()}: "{searchQuery}"
                  </span>
                  <button
                    onclick={clearSearch}
                    class="rounded-full p-0.5 transition-all duration-150 hover:scale-110 hover:bg-amber-100 dark:hover:bg-amber-900"
                  >
                    <IconXMark class="h-3 w-3 text-amber-700 dark:text-amber-300" />
                  </button>
                </span>
              {/if}

              <!-- Clear all (ghost button with icon) - accessible hover with 4.5:1+ contrast -->
              <button
                onclick={clearFilters}
                class="text-muted ml-2 inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-all
                duration-150 hover:bg-red-600 hover:text-white
                focus:outline-none focus-visible:ring-2
                focus-visible:ring-red-500 focus-visible:ring-offset-2 active:scale-95 dark:hover:bg-red-500
                dark:hover:text-white"
              >
                <Trash2 class="h-3.5 w-3.5" />
                {m.audit_clear_all()}
              </button>
            </div>
          {/if}

          <!-- Results Summary and Top Pagination -->
          <div class="bg-subtle mb-6 rounded-lg p-4">
            <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div class="flex items-center gap-3">
                <p class="text-default text-sm font-medium">
                  {m.audit_showing_results({ shown: logs.length, total: totalCount })}
                </p>
                {#if totalPages > 1}
                  <span class="text-muted border-default border-l pl-3 text-sm">
                    {m.audit_page_info({ current: currentPage, total: totalPages })}
                  </span>
                {/if}
              </div>

              {#if totalPages > 1}
                <div class="flex items-center gap-3">
                  <Button
                    onclick={prevPage}
                    disabled={currentPage <= 1}
                    variant="outlined"
                    size="sm"
                    class="min-w-[100px]"
                  >
                    {m.audit_previous()}
                  </Button>
                  <Button
                    onclick={nextPage}
                    disabled={currentPage >= totalPages}
                    variant="outlined"
                    size="sm"
                    class="min-w-[100px]"
                  >
                    {m.audit_next()}
                  </Button>
                </div>
              {/if}
            </div>
          </div>

          <!-- Audit Logs Table -->
          <div class="border-default bg-primary rounded-lg border shadow-sm">
            <div class="overflow-x-auto">
              <table class="w-full">
                <thead class="border-accent-default/20 bg-subtle sticky top-0 border-b-2">
                  <tr>
                    <th class="w-8 px-4 py-3"></th>
                    <th
                      class="text-default w-[15%] px-4 py-3 text-left text-xs font-semibold tracking-wider uppercase"
                    >
                      {m.audit_timestamp()}
                    </th>
                    <th
                      class="text-default w-[15%] px-4 py-3 text-left text-xs font-semibold tracking-wider uppercase"
                    >
                      {m.audit_action()}
                    </th>
                    <th
                      class="text-default w-[45%] px-4 py-3 text-left text-xs font-semibold tracking-wider uppercase"
                    >
                      {m.audit_description()}
                    </th>
                    <th
                      class="text-default w-[18%] px-4 py-3 text-left text-xs font-semibold tracking-wider uppercase"
                    >
                      {m.audit_actor()}
                    </th>
                    <th
                      class="text-default w-[7%] px-4 py-3 text-center text-xs font-semibold tracking-wider uppercase"
                    >
                      {m.audit_status()}
                    </th>
                  </tr>
                </thead>
                <tbody class="divide-default bg-primary divide-y">
                  {#if logs.length === 0}
                    <tr>
                      <td colspan="6" class="px-4 py-16 text-center">
                        <div class="flex flex-col items-center gap-3">
                          <IconCalendar class="text-muted h-12 w-12 opacity-50" />
                          <div>
                            <p class="text-default text-sm font-medium">
                              {m.audit_no_logs_found()}
                            </p>
                            <p class="text-muted mt-1 text-xs">
                              {activeFilterCount > 0
                                ? m.audit_try_adjusting_filters()
                                : m.audit_logs_will_appear()}
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
                    {#each logs as log, index (log.id || index)}
                      {@const isExpanded = expandedRows.has(log.id || index.toString())}
                      <!-- Main Row -->
                      <tr
                        class="hover:bg-hover/70 cursor-pointer transition-colors duration-150"
                        onclick={() => toggleRowExpansion(log.id || index.toString())}
                      >
                        <td class="px-4 py-3">
                          <div class="hover:bg-hover rounded-md p-1 transition-colors duration-150">
                            <IconChevronDown
                              class={`text-muted h-5 w-5 transition-transform duration-200 ${isExpanded ? "rotate-180" : ""}`}
                            />
                          </div>
                        </td>
                        <td class="px-4 py-3">
                          <div class="flex flex-col">
                            <span
                              class="text-default text-sm font-medium"
                              title={formatFullTimestamp(log.timestamp)}
                            >
                              {formatTimestamp(log.timestamp)}
                            </span>
                            <span class="text-muted text-xs">
                              {new Date(log.timestamp).toLocaleTimeString(getLocale())}
                            </span>
                          </div>
                        </td>
                        <td class="px-4 py-3">
                          <span
                            class={`inline-flex rounded-md px-2.5 py-1 text-xs font-medium shadow-sm ${getActionBadgeClass(log.action)}`}
                          >
                            {getActionLabel(log.action as ActionType)}
                          </span>
                        </td>
                        <td class="px-4 py-3">
                          <p class="text-default line-clamp-2 text-sm" title={log.description}>
                            {log.description}
                          </p>
                        </td>
                        <td class="px-4 py-3">
                          <div class="flex flex-col">
                            <span class="text-default truncate text-sm">
                              {(log.metadata as Record<string, Record<string, string>>)?.actor
                                ?.name || "System"}
                            </span>
                            {#if (log.metadata as Record<string, Record<string, string>>)?.actor?.email}
                              <span class="text-muted truncate text-xs">
                                {(log.metadata as Record<string, Record<string, string>>).actor
                                  .email}
                              </span>
                            {/if}
                          </div>
                        </td>
                        <td class="px-4 py-3">
                          {#if log.outcome === "success"}
                            <span
                              class="inline-flex items-center gap-1 rounded-md border border-green-200 bg-green-50 px-2 py-1 text-xs font-medium text-green-900 transition-transform duration-150 hover:scale-105 dark:border-green-800 dark:bg-green-950 dark:text-green-300"
                            >
                              <CircleCheck class="h-3.5 w-3.5" />
                              {m.audit_success()}
                            </span>
                          {:else}
                            <span
                              class="inline-flex items-center gap-1 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs font-medium text-red-900 transition-transform duration-150 hover:scale-105 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
                            >
                              <CircleX class="h-3.5 w-3.5" />
                              {m.audit_failure()}
                            </span>
                          {/if}
                        </td>
                      </tr>

                      <!-- Expanded Metadata Row -->
                      {#if isExpanded}
                        <tr transition:slide={{ duration: 200 }}>
                          <td colspan="6" class="bg-subtle px-4 py-4">
                            <div class="mx-auto max-w-5xl space-y-3">
                              <h4
                                class="text-default text-xs font-semibold tracking-wider uppercase"
                              >
                                {m.audit_full_details()}
                              </h4>
                              <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                                <div class="border-default bg-primary rounded-lg border p-3">
                                  <p class="text-muted mb-1 text-xs font-medium">
                                    {m.audit_full_timestamp()}
                                  </p>
                                  <p class="text-default text-sm">
                                    {formatFullTimestamp(log.timestamp)}
                                  </p>
                                </div>
                                <div class="border-default bg-primary rounded-lg border p-3">
                                  <p class="text-muted mb-1 text-xs font-medium">
                                    {m.audit_outcome()}
                                  </p>
                                  <p class="text-default text-sm">
                                    {log.outcome === "success"
                                      ? m.audit_success()
                                      : m.audit_failure()}
                                  </p>
                                </div>
                              </div>
                              {#if log.metadata && Object.keys(log.metadata).length > 0}
                                <div class="border-default bg-primary rounded-lg border p-3">
                                  <div class="mb-2 flex items-center justify-between">
                                    <p class="text-muted text-xs font-medium">
                                      {m.audit_metadata_json()}
                                    </p>
                                    <button
                                      onclick={() =>
                                        copyJsonToClipboard(
                                          log.metadata,
                                          log.id || index.toString()
                                        )}
                                      class="text-muted hover:bg-hover hover:text-default flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium transition-all duration-150 hover:scale-105 active:scale-95"
                                      aria-label={m.audit_copy_json()}
                                    >
                                      {#if copiedRowId === (log.id || index.toString())}
                                        <IconCheck
                                          class="h-3.5 w-3.5 text-green-600 dark:text-green-400"
                                        />
                                        <span class="text-green-600 dark:text-green-400"
                                          >{m.audit_json_copied()}</span
                                        >
                                      {:else}
                                        <IconCopy class="h-3.5 w-3.5" />
                                        {m.audit_copy_json()}
                                      {/if}
                                    </button>
                                  </div>
                                  <!-- eslint-disable svelte/no-at-html-tags -->
                                  <pre
                                    class="max-h-96 overflow-auto rounded border border-gray-200 bg-gray-50 p-3 font-mono text-xs break-words whitespace-pre-wrap text-gray-800 dark:border-gray-800 dark:bg-gray-950 dark:text-gray-200">{@html formatJsonWithSyntaxHighlighting(
                                      log.metadata
                                    )}</pre>
                                  <!-- eslint-enable svelte/no-at-html-tags -->
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
          {#if totalPages > 1}
            <div class="bg-subtle mt-8 rounded-lg p-4">
              <div class="flex items-center justify-center gap-4">
                <Button
                  onclick={prevPage}
                  disabled={currentPage <= 1}
                  variant="outlined"
                  class="min-w-[120px] transition-transform duration-150 hover:scale-[1.02] active:scale-[0.98]"
                >
                  {m.audit_previous()}
                </Button>
                <span class="bg-primary border-default rounded-md border px-4 py-2 text-sm">
                  {m.audit_page()} <span class="text-default font-semibold">{currentPage}</span>
                  {m.audit_of()} <span class="text-default font-semibold">{totalPages}</span>
                </span>
                <Button
                  onclick={nextPage}
                  disabled={currentPage >= totalPages}
                  variant="outlined"
                  class="min-w-[120px] transition-transform duration-150 hover:scale-[1.02] active:scale-[0.98]"
                >
                  {m.audit_next()}
                </Button>
              </div>
            </div>
          {/if}
        </div>
        <!-- End of logs tab container -->
      {/if}
      <!-- End of justification check -->
    {:else if activeTab === "config"}
      <!-- Configuration Tab Content -->
      <div class="px-4 pb-8 sm:px-6 lg:px-8">
        <AuditConfigTab />
      </div>
    {/if}
  </Page.Main>
</Page.Root>
