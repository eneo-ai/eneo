<script lang="ts">
  import { goto, replaceState } from "$app/navigation";
  import { page } from "$app/stores";
  import { writable } from "svelte/store";
  import { Page } from "$lib/components/layout";
  import { Button, Input, Select, Dropdown, ProgressBar } from "@intric/ui";
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
  import { IconCopy } from "@intric/icons/copy";
  import { IconCheck } from "@intric/icons/check";
  import { CircleCheck, CircleX, Calendar, Shield, FileText, Settings, Trash2 } from "lucide-svelte";
  import { fade, slide, scale } from "svelte/transition";
  import { onDestroy } from "svelte";
  import { getIntric } from "$lib/core/Intric";
  import { getLocale } from "$lib/paraglide/runtime";
  import AuditConfigTab from "./AuditConfigTab.svelte";
  import AccessJustificationForm from "./AccessJustificationForm.svelte";

  type AuditLogResponse = components["schemas"]["AuditLogResponse"];
  type ActionType = components["schemas"]["ActionType"];

  let { data } = $props();

  const intric = getIntric();

  // Local state for audit logs (shadows data from load function to allow client-side updates)
  let logs = $state<AuditLogResponse[]>(data.logs || []);
  let totalCount = $state(data.total_count || 0);
  let currentPage = $state(data.page || 1);
  let pageSize = $state(data.page_size || 100);
  let totalPages = $state(data.total_pages || 0);
  let hasSessionState = $state(data.hasSession);
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
  let activeTab = $state<'logs' | 'config'>('logs');

  // Check URL for tab parameter
  $effect(() => {
    const tab = $page.url.searchParams.get('tab');
    if (tab === 'config') {
      activeTab = 'config';
    } else {
      activeTab = 'logs';
    }
  });

  // Update URL when tab changes
  function switchTab(tab: 'logs' | 'config') {
    activeTab = tab;
    const params = new URLSearchParams($page.url.search);
    if (tab === 'config') {
      params.set('tab', 'config');
    } else {
      params.delete('tab');
    }
    const url = params.toString() ? `/admin/audit-logs?${params.toString()}` : '/admin/audit-logs';
    goto(url, { noScroll: true, keepFocus: true });
  }

  // Handle access justification submission
  async function handleJustificationSubmit(justification: { category: string; description: string }) {
    try {
      // Create audit access session (sets HTTP-only cookie with session ID)
      await intric.audit.createAccessSession({
        category: justification.category,
        description: justification.description
      });

      // Reload page - session cookie is now set, grants access to audit logs
      await goto('/admin/audit-logs', { invalidateAll: true });
    } catch (error) {
      console.error("Failed to create audit access session:", error);
      // Error will be shown by the form component
      throw error;
    }
  }

  // Expandable row state
  let expandedRows = $state<Set<string>>(new Set());
  let copiedRowId = $state<string | null>(null);

  // Filter states
  let dateRange = $state<{ start: CalendarDate | undefined; end: CalendarDate | undefined }>({
    start: undefined,
    end: undefined
  });
  let selectedAction = $state<ActionType | "all">("all");
  let selectedActions = $state<ActionType[]>([]);  // Multi-select support
  let showActionDropdown = $state(false);  // For multi-select dropdown
  let selectedUser = $state<UserSparse | null>(null);
  let userSearchResults = $state<UserSparse[]>([]);
  let isSearchingUsers = $state(false);
  let showUserDropdown = $state(false);
  let userSearchCompleted = $state(false); // Track if search has completed (for empty state)

  // Unified scoped search state
  let searchScope = $state<'entity' | 'user'>('entity');
  let searchQuery = $state("");
  let showScopeDropdown = $state(false);
  let debounceTimer: ReturnType<typeof setTimeout>;
  let userSearchTimer: ReturnType<typeof setTimeout>;
  let entitySearchTimer: ReturnType<typeof setTimeout>;  // Debounce for entity search
  let isExporting = $state(false);
  let exportProgress = $state(0);
  let exportJobId = $state<string | null>(null);
  let exportStatus = $state<string | null>(null);
  let exportError = $state<string | null>(null);
  let exportProcessedRecords = $state(0);
  let exportTotalRecords = $state(0);
  let pollTimer: ReturnType<typeof setTimeout>;
  let isInitializingFromUrl = false;  // Flag to prevent auto-apply during URL initialization

  // Retention policy state - initialize from server data
  let retentionDays = $state<number>(data.retentionPolicy?.retention_days ?? 365);
  let isEditingRetention = $state(false);
  let retentionInputValue = $state<number>(data.retentionPolicy?.retention_days ?? 365);
  let isSavingRetention = $state(false);
  let retentionError = $state<string | null>(null);

  // Track active quick filter preset (7, 30, 90 days, or null)
  let activePreset = $state<7 | 30 | 90 | null>(null);

  // Get translated label for action type
  function getActionLabel(action: ActionType | "all"): string {
    const labels: Record<ActionType | "all", () => string> = {
      all: m.audit_all_actions,
      user_created: m.audit_action_user_created,
      user_updated: m.audit_action_user_updated,
      user_deleted: m.audit_action_user_deleted,
      role_modified: m.audit_action_role_modified,
      permission_changed: m.audit_action_permission_changed,
      tenant_settings_updated: m.audit_action_tenant_settings_updated,
      credentials_updated: m.audit_action_credentials_updated,
      federation_updated: m.audit_action_federation_updated,
      assistant_created: m.audit_action_assistant_created,
      assistant_updated: m.audit_action_assistant_updated,
      assistant_deleted: m.audit_action_assistant_deleted,
      space_created: m.audit_action_space_created,
      space_updated: m.audit_action_space_updated,
      space_member_added: m.audit_action_space_member_added,
      space_member_removed: m.audit_action_space_member_removed,
      app_created: m.audit_action_app_created,
      app_updated: m.audit_action_app_updated,
      app_deleted: m.audit_action_app_deleted,
      app_executed: m.audit_action_app_executed,
      session_started: m.audit_action_session_started,
      session_ended: m.audit_action_session_ended,
      file_uploaded: m.audit_action_file_uploaded,
      file_deleted: m.audit_action_file_deleted,
      website_crawled: m.audit_action_website_crawled,
      website_created: m.audit_action_website_created,
      website_updated: m.audit_action_website_updated,
      website_deleted: m.audit_action_website_deleted,
      website_transferred: m.audit_action_website_transferred,
      api_key_generated: m.audit_action_api_key_generated,
      retention_policy_applied: m.audit_action_retention_policy_applied,
      role_created: m.audit_action_role_created,
      role_deleted: m.audit_action_role_deleted,
      assistant_transferred: m.audit_action_assistant_transferred,
      assistant_published: m.audit_action_assistant_published,
      app_published: m.audit_action_app_published,
      app_run_deleted: m.audit_action_app_run_deleted,
      space_deleted: m.audit_action_space_deleted,
      group_chat_created: m.audit_action_group_chat_created,
      collection_created: m.audit_action_collection_created,
      template_created: m.audit_action_template_created,
      template_updated: m.audit_action_template_updated,
      template_deleted: m.audit_action_template_deleted,
      module_added: m.audit_action_module_added,
      module_added_to_tenant: m.audit_action_module_added_to_tenant,
      security_classification_created: m.audit_action_security_classification_created,
      security_classification_updated: m.audit_action_security_classification_updated,
      security_classification_deleted: m.audit_action_security_classification_deleted,
      security_classification_levels_updated: m.audit_action_security_classification_levels_updated,
      security_classification_enabled: m.audit_action_security_classification_enabled,
      security_classification_disabled: m.audit_action_security_classification_disabled,
      collection_updated: m.audit_action_collection_updated,
      collection_deleted: m.audit_action_collection_deleted,
      integration_added: m.audit_action_integration_added,
      integration_removed: m.audit_action_integration_removed,
      integration_connected: m.audit_action_integration_connected,
      integration_disconnected: m.audit_action_integration_disconnected,
      integration_knowledge_created: m.audit_action_integration_knowledge_created,
      integration_knowledge_deleted: m.audit_action_integration_knowledge_deleted,
      completion_model_updated: m.audit_action_completion_model_updated,
      embedding_model_updated: m.audit_action_embedding_model_updated,
      transcription_model_updated: m.audit_action_transcription_model_updated,
      audit_log_viewed: m.audit_action_audit_log_viewed,
      audit_log_exported: m.audit_action_audit_log_exported,
      audit_session_created: m.audit_action_audit_session_created,
    };
    return labels[action]?.() || action;
  }

  // Action type options with better categorization
  const actionOptions = $derived([
    { value: "all" as const, label: m.audit_all_actions() },
    { value: "user_created" as ActionType, label: m.audit_action_user_created(), category: "admin" },
    { value: "user_updated" as ActionType, label: m.audit_action_user_updated(), category: "admin" },
    { value: "user_deleted" as ActionType, label: m.audit_action_user_deleted(), category: "admin" },
    { value: "role_modified" as ActionType, label: m.audit_action_role_modified(), category: "admin" },
    { value: "permission_changed" as ActionType, label: m.audit_action_permission_changed(), category: "admin" },
    { value: "tenant_settings_updated" as ActionType, label: m.audit_action_tenant_settings_updated(), category: "admin" },
    { value: "credentials_updated" as ActionType, label: m.audit_action_credentials_updated(), category: "admin" },
    { value: "federation_updated" as ActionType, label: m.audit_action_federation_updated(), category: "admin" },
    { value: "api_key_generated" as ActionType, label: m.audit_action_api_key_generated(), category: "admin" },
    { value: "assistant_created" as ActionType, label: m.audit_action_assistant_created(), category: "user" },
    { value: "assistant_updated" as ActionType, label: m.audit_action_assistant_updated(), category: "user" },
    { value: "assistant_deleted" as ActionType, label: m.audit_action_assistant_deleted(), category: "user" },
    { value: "space_created" as ActionType, label: m.audit_action_space_created(), category: "user" },
    { value: "space_updated" as ActionType, label: m.audit_action_space_updated(), category: "user" },
    { value: "space_member_added" as ActionType, label: m.audit_action_space_member_added(), category: "user" },
    { value: "space_member_removed" as ActionType, label: m.audit_action_space_member_removed(), category: "user" },
    { value: "app_created" as ActionType, label: m.audit_action_app_created(), category: "user" },
    { value: "app_updated" as ActionType, label: m.audit_action_app_updated(), category: "user" },
    { value: "app_deleted" as ActionType, label: m.audit_action_app_deleted(), category: "user" },
    { value: "app_executed" as ActionType, label: m.audit_action_app_executed(), category: "user" },
    { value: "session_started" as ActionType, label: m.audit_action_session_started(), category: "user" },
    { value: "session_ended" as ActionType, label: m.audit_action_session_ended(), category: "user" },
    { value: "file_uploaded" as ActionType, label: m.audit_action_file_uploaded(), category: "user" },
    { value: "file_deleted" as ActionType, label: m.audit_action_file_deleted(), category: "user" },
    { value: "website_crawled" as ActionType, label: m.audit_action_website_crawled(), category: "system" },
    { value: "website_created" as ActionType, label: m.audit_action_website_created(), category: "user" },
    { value: "website_updated" as ActionType, label: m.audit_action_website_updated(), category: "user" },
    { value: "website_deleted" as ActionType, label: m.audit_action_website_deleted(), category: "user" },
    { value: "website_transferred" as ActionType, label: m.audit_action_website_transferred(), category: "user" },
    { value: "role_created" as ActionType, label: m.audit_action_role_created(), category: "admin" },
    { value: "role_deleted" as ActionType, label: m.audit_action_role_deleted(), category: "admin" },
    { value: "assistant_transferred" as ActionType, label: m.audit_action_assistant_transferred(), category: "user" },
    { value: "assistant_published" as ActionType, label: m.audit_action_assistant_published(), category: "user" },
    { value: "app_published" as ActionType, label: m.audit_action_app_published(), category: "user" },
    { value: "app_run_deleted" as ActionType, label: m.audit_action_app_run_deleted(), category: "user" },
    { value: "space_deleted" as ActionType, label: m.audit_action_space_deleted(), category: "user" },
    { value: "group_chat_created" as ActionType, label: m.audit_action_group_chat_created(), category: "user" },
    { value: "collection_created" as ActionType, label: m.audit_action_collection_created(), category: "user" },
    { value: "collection_updated" as ActionType, label: m.audit_action_collection_updated(), category: "user" },
    { value: "collection_deleted" as ActionType, label: m.audit_action_collection_deleted(), category: "user" },
    { value: "integration_added" as ActionType, label: m.audit_action_integration_added(), category: "admin" },
    { value: "integration_removed" as ActionType, label: m.audit_action_integration_removed(), category: "admin" },
    { value: "integration_connected" as ActionType, label: m.audit_action_integration_connected(), category: "user" },
    { value: "integration_disconnected" as ActionType, label: m.audit_action_integration_disconnected(), category: "user" },
    { value: "integration_knowledge_created" as ActionType, label: m.audit_action_integration_knowledge_created(), category: "user" },
    { value: "integration_knowledge_deleted" as ActionType, label: m.audit_action_integration_knowledge_deleted(), category: "user" },
    { value: "completion_model_updated" as ActionType, label: m.audit_action_completion_model_updated(), category: "admin" },
    { value: "embedding_model_updated" as ActionType, label: m.audit_action_embedding_model_updated(), category: "admin" },
    { value: "transcription_model_updated" as ActionType, label: m.audit_action_transcription_model_updated(), category: "admin" },
    { value: "template_created" as ActionType, label: m.audit_action_template_created(), category: "admin" },
    { value: "template_updated" as ActionType, label: m.audit_action_template_updated(), category: "admin" },
    { value: "template_deleted" as ActionType, label: m.audit_action_template_deleted(), category: "admin" },
    { value: "module_added" as ActionType, label: m.audit_action_module_added(), category: "system" },
    { value: "module_added_to_tenant" as ActionType, label: m.audit_action_module_added_to_tenant(), category: "system" },
    { value: "security_classification_created" as ActionType, label: m.audit_action_security_classification_created(), category: "admin" },
    { value: "security_classification_updated" as ActionType, label: m.audit_action_security_classification_updated(), category: "admin" },
    { value: "security_classification_deleted" as ActionType, label: m.audit_action_security_classification_deleted(), category: "admin" },
    { value: "security_classification_levels_updated" as ActionType, label: m.audit_action_security_classification_levels_updated(), category: "admin" },
    { value: "security_classification_enabled" as ActionType, label: m.audit_action_security_classification_enabled(), category: "admin" },
    { value: "security_classification_disabled" as ActionType, label: m.audit_action_security_classification_disabled(), category: "admin" },
    { value: "retention_policy_applied" as ActionType, label: m.audit_action_retention_policy_applied(), category: "system" },
    { value: "audit_log_viewed" as ActionType, label: m.audit_action_audit_log_viewed(), category: "system" },
    { value: "audit_log_exported" as ActionType, label: m.audit_action_audit_log_exported(), category: "system" },
    { value: "audit_session_created" as ActionType, label: m.audit_action_audit_session_created(), category: "system" },
  ]);

  // Create store for Select component
  const actionStore = writable<{ value: ActionType | "all"; label: string }>({
    value: "all",
    label: m.audit_all_actions()
  });

  // Watch store changes and apply filters
  $effect(() => {
    const newAction = $actionStore.value;
    if (selectedAction !== newAction) {
      selectedAction = newAction;
      if (!isInitializingFromUrl) {
        applyFilters();
      }
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
    isInitializingFromUrl = true;

    // Set entity search from URL
    if (search) {
      searchScope = 'entity';
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
      selectedAction = "all";  // Keep legacy state at default
    } else if (action && action !== "all") {
      // Legacy single-action support (backwards compatible)
      selectedAction = action as ActionType;
      selectedActions = [action as ActionType];
      const option = actionOptions.find(opt => opt.value === action);
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
      isInitializingFromUrl = false;
    });
  });

  // Date preset functions (toggle behavior - click again to deselect)
  function setDatePreset(days: 7 | 30 | 90) {
    // Toggle off if clicking the same preset
    if (activePreset === days) {
      dateRange = { start: undefined, end: undefined };
      activePreset = null;
      applyFilters();
      return;
    }

    const tz = getLocalTimeZone();
    const endDate = today(tz); // Set to current day (applyFilters will add 1 day to make it inclusive)
    const startDate = today(tz).subtract({ days: days - 1 }); // Subtract days-1 to get actual range
    dateRange = { start: startDate, end: endDate };
    activePreset = days; // Track which preset is active
    applyFilters();
  }

  // Helper function to detect which preset matches a date range
  function detectPresetFromDateRange(start: CalendarDate | undefined, end: CalendarDate | undefined): 7 | 30 | 90 | null {
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

  function formatJsonWithSyntaxHighlighting(obj: any): string {
    const json = JSON.stringify(obj, null, 2);
    return json
      .replace(/"([^"]+)":/g, '<span class="text-blue-600 dark:text-blue-400">"$1"</span>:')  // Keys
      .replace(/: "([^"]*)"/g, ': <span class="text-green-600 dark:text-green-400">"$1"</span>')  // String values
      .replace(/: (\d+)/g, ': <span class="text-orange-600 dark:text-orange-400">$1</span>')  // Numbers
      .replace(/: (true|false|null)/g, ': <span class="text-purple-600 dark:text-purple-400">$1</span>');  // Booleans/null
  }

  function getActionBadgeClass(action: string): string {
    // Admin/security actions (critical - needs attention) - RED
    const adminActions = ["user_created", "user_updated", "user_deleted", "role_modified", "permission_changed", "tenant_settings_updated"];

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
    expandedRows = new Set(expandedRows); // Trigger reactivity
  }

  async function copyJsonToClipboard(json: any, logId: string) {
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

    const params = new URLSearchParams();

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
      page_size: pageSize,
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

    if (searchScope === 'entity' && searchQuery.length >= 3) {
      params.set("search", searchQuery);
      filterParams.search = searchQuery;
    }

    if (activeTab === 'config') {
      params.set("tab", "config");
    }

    // Update URL without triggering navigation (preserves session)
    const url = params.toString() ? `/admin/audit-logs?${params.toString()}` : "/admin/audit-logs";
    replaceState(url, {});

    // Fetch data directly without triggering load function
    try {
      isFiltering = true;
      const response = await intric.audit.list(filterParams);
      logs = response.logs || [];
      totalCount = response.total_count || 0;
      currentPage = response.page || 1;
      totalPages = response.total_pages || 0;
    } catch (error: any) {
      // Ignore abort errors (request was cancelled by a newer request)
      if (error?.name === 'AbortError') return;

      // If 401, session expired - show justification form
      if (error?.status === 401) {
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
    selectedActions = [];  // Clear multi-select
    actionStore.set({ value: "all", label: m.audit_all_actions() });
    selectedUser = null;
    searchQuery = "";
    searchScope = 'entity';
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

    if (searchScope === 'entity') {
      // Entity search logic
      clearTimeout(entitySearchTimer);
      if (query.length >= 3 || query.length === 0) {
        entitySearchTimer = setTimeout(() => {
          applyFilters();
        }, 300);
      }
    } else {
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
            page_size: 10,
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
    applyFilters();
  }

  function clearUserFilter() {
    selectedUser = null;
    if (searchScope === 'user') {
      searchQuery = "";
    }
    userSearchResults = [];
    showUserDropdown = false;
    userSearchCompleted = false;
    applyFilters();
  }

  function clearSearch() {
    searchQuery = "";
    clearTimeout(entitySearchTimer);
    clearTimeout(userSearchTimer);
    userSearchResults = [];
    showUserDropdown = false;
    userSearchCompleted = false;
    if (searchScope === 'entity') {
      applyFilters();
    }
  }

  // Debounced timer for action multi-select
  let actionDebounceTimer: ReturnType<typeof setTimeout>;

  // Toggle action selection with debounced filter application
  function toggleAction(actionValue: ActionType) {
    if (selectedActions.includes(actionValue)) {
      selectedActions = selectedActions.filter(a => a !== actionValue);
    } else {
      selectedActions = [...selectedActions, actionValue];
    }

    // Debounce filter application to reduce API calls during rapid selections
    clearTimeout(actionDebounceTimer);
    actionDebounceTimer = setTimeout(() => {
      applyFilters();
    }, 500);  // 500ms debounce for multi-select
  }

  // Handle scope change - preserve query and re-trigger search in new scope
  function handleScopeChange(newScope: 'entity' | 'user') {
    // Clear ALL pending search timers to prevent race conditions
    clearTimeout(entitySearchTimer);
    clearTimeout(userSearchTimer);

    searchScope = newScope;
    showScopeDropdown = false;

    // Reset user-specific state when switching away from user scope
    if (newScope === 'entity') {
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
    if (showScopeDropdown && !target.closest('.scope-dropdown-container')) {
      showScopeDropdown = false;
    }
    if (showUserDropdown && !target.closest('.user-dropdown-container')) {
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
      const requestBody: Record<string, any> = {
        format: format === "json" ? "jsonl" : "csv",
      };

      // Add filter parameters
      if (params.get("from_date")) {
        requestBody.from_date = params.get("from_date");
      }
      if (params.get("to_date")) {
        requestBody.to_date = params.get("to_date");
      }
      if (params.get("action") && params.get("action") !== "all") {
        requestBody.action = params.get("action");
      }
      if (params.get("actor_id")) {
        requestBody.actor_id = params.get("actor_id");
      }

      // 1. Request async export
      const response = await fetch("/admin/audit-logs/export/async", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
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
          const dateStr = (dateRange?.start && dateRange?.end)
            ? `${dateRange.start.toString()}_to_${dateRange.end.toString()}`
            : new Date().toISOString().split('T')[0];
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
        method: "POST",
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

  // Auto-apply filters on any filter change (consolidated for performance)
  $effect(() => {
    // Skip auto-apply when initializing from URL to prevent redirect loops
    if (isInitializingFromUrl) return;

    // Track filter changes and apply with debounce
    const hasDateFilter = dateRange?.start && dateRange?.end;
    const hasActionFilter = selectedActions.length > 0;

    // Only auto-apply if we're not in the initial load state
    // Debounce for 2.5 seconds to reduce audit log noise (hybrid logging approach)
    if (hasDateFilter || hasActionFilter) {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        applyFilters();
      }, 2500);
    }
  });

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
    selectedActions.length +  // Count each selected action as a filter
    (selectedUser ? 1 : 0) +
    (searchScope === 'entity' && searchQuery.length >= 3 ? 1 : 0)
  );

  // Retention policy functions
  async function saveRetentionPolicy() {
    try {
      isSavingRetention = true;
      retentionError = null;

      if (retentionInputValue < 1 || retentionInputValue > 2555) {
        retentionError = "Retention period must be between 1 and 2555 days";
        return;
      }

      const updated = await intric.audit.updateRetentionPolicy({
        retention_days: retentionInputValue
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
    retentionInputValue = retentionDays;
    isEditingRetention = false;
    retentionError = null;
  }

  // Calculate cutoff date for retention
  function getRetentionCutoffDate(days: number): string {
    const cutoff = new Date();
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
    {#if activeTab === 'logs' && hasSession}
      {#if isExporting}
        <!-- Export Progress UI -->
        <div class="flex items-center gap-3">
          <div class="flex flex-col gap-1 min-w-[200px]">
            <div class="flex items-center justify-between text-xs">
              <span class="text-muted">
                {exportStatus === "pending" ? m.audit_export_preparing() : m.audit_exporting()}
              </span>
              <span class="font-medium text-default">{exportProgress}%</span>
            </div>
            <ProgressBar progress={exportProgress} />
            {#if exportTotalRecords > 0}
              <span class="text-xs text-muted">
                {exportProcessedRecords.toLocaleString()} / {exportTotalRecords.toLocaleString()} {m.audit_records()}
              </span>
            {/if}
          </div>
          <Button variant="ghost" onclick={cancelExport} class="text-red-600 hover:text-red-700 hover:bg-red-50 dark:text-red-400 dark:hover:text-red-300 dark:hover:bg-red-950">
            <IconXMark class="h-4 w-4" />
            {m.audit_cancel()}
          </Button>
        </div>
      {:else if exportError}
        <!-- Export Error UI -->
        <div class="flex items-center gap-3">
          <div class="flex items-center gap-2 rounded-md bg-red-50 dark:bg-red-950 px-3 py-2 text-sm text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800">
            <IconInfo class="h-4 w-4" />
            <span>{exportError}</span>
          </div>
          <Button variant="ghost" onclick={resetExportState}>
            <IconXMark class="h-4 w-4" />
          </Button>
        </div>
      {:else}
        <!-- Normal Export Buttons -->
        <div class="flex gap-[1px]">
          <Button variant="primary" onclick={() => exportLogs("csv")} disabled={isExporting} class="!rounded-r-none">
            <IconDownload class="h-4 w-4" />
            Export ({totalCount})
          </Button>
          <Dropdown.Root gutter={2} arrowSize={0} placement="bottom-end">
            <Dropdown.Trigger asFragment let:trigger>
              <Button padding="icon" variant="primary" is={trigger} disabled={isExporting} class="!rounded-l-none">
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
    {#if !(activeTab === 'logs' && !hasSession)}
    <!-- Description with better spacing and visual treatment -->
    <div class="mb-6 pt-4 px-4 sm:px-6 lg:px-8">
      <p class="text-sm text-muted leading-relaxed">
        {m.audit_logs_description()}
      </p>
    </div>

    <!-- Tabs with improved styling -->
    <div class="mb-6 px-4 sm:px-6 lg:px-8">
      <div class="inline-flex gap-1 p-1.5 bg-subtle rounded-lg border border-default shadow-sm">
        <button
          onclick={() => switchTab('logs')}
          class={`flex items-center justify-center gap-2 px-6 py-2.5 rounded-md text-sm font-semibold transition-all duration-150 ${
            activeTab === 'logs'
              ? 'bg-accent-default text-on-fill shadow-md ring-1 ring-accent-default/20 shadow-accent-default/25'
              : 'text-muted hover:text-default hover:bg-hover hover:scale-[1.02] active:scale-[0.98]'
          }`}
        >
          <FileText class="h-4 w-4" />
          {m.audit_tab_logs()}
        </button>
        <button
          onclick={() => switchTab('config')}
          class={`flex items-center justify-center gap-2 px-6 py-2.5 rounded-md text-sm font-semibold transition-all duration-150 ${
            activeTab === 'config'
              ? 'bg-accent-default text-on-fill shadow-md ring-1 ring-accent-default/20 shadow-accent-default/25'
              : 'text-muted hover:text-default hover:bg-hover hover:scale-[1.02] active:scale-[0.98]'
          }`}
        >
          <Settings class="h-4 w-4" />
          {m.audit_tab_config()}
        </button>
      </div>
    </div>
    {/if}

      {#if activeTab === 'logs'}
        <!-- Logs Tab Content -->
        {#if !hasSession}
          <!-- Access Justification Form -->
          <AccessJustificationForm onSubmit={handleJustificationSubmit} />
        {:else}
        <div class="px-4 pb-8 sm:px-6 lg:px-8">
        <!-- Retention Policy Section -->
        <div class="mb-8 rounded-xl border border-default bg-subtle p-5 transition-shadow duration-200 hover:shadow-md">
          <div class="flex items-center justify-between mb-3">
            <div class="flex items-center gap-2.5">
              <div class="rounded-lg bg-accent/10 p-1.5">
                <Shield class="h-5 w-5 text-accent" />
              </div>
              <div>
                <h3 class="text-sm font-semibold text-default">{m.audit_retention_policy()}</h3>
                <p class="text-xs text-muted mt-0.5">Automatisk borttagning av gamla granskningsloggar</p>
              </div>
            </div>
            {#if !isEditingRetention}
              <Button onclick={() => (isEditingRetention = true)} variant="ghost" size="sm" class="min-w-[80px]">
                {m.audit_retention_edit()}
              </Button>
            {/if}
          </div>

          {#if !isEditingRetention}
            <!-- Display Mode -->
            <div class="rounded-lg bg-primary p-4 space-y-2" transition:slide={{ duration: 200 }}>
              <div class="flex items-start gap-3">
                <div class="rounded-md bg-accent/10 p-1.5">
                  <Calendar class="h-4 w-4 text-accent" />
                </div>
                <div class="flex-1">
                  <div class="flex items-baseline gap-2 mb-1">
                    <span class="text-lg font-semibold text-default">{retentionDays}</span>
                    <span class="text-xs text-muted">
                      {retentionDays === 1 ? 'dag' : 'dagar'}
                      {retentionDays === 365 ? ` (1 ${m.audit_retention_year()})` : retentionDays === 730 ? ` (2 ${m.audit_retention_years()})` : retentionDays === 90 ? ` (3 ${m.audit_retention_months()})` : retentionDays === 2555 ? ` (7 ${m.audit_retention_years()})` : ''}
                    </span>
                  </div>
                  <p class="text-xs text-muted leading-relaxed">
                    {m.audit_retention_cutoff({ date: getRetentionCutoffDate(retentionDays) })}
                  </p>
                </div>
              </div>
            </div>
          {:else}
            <!-- Edit Mode -->
            <div class="space-y-3" transition:slide={{ duration: 200 }}>
              <div class="rounded-lg bg-primary p-4 space-y-3">
                <div class="max-w-xl">
                  <!-- svelte-ignore a11y_label_has_associated_control -->
                  <label class="text-xs font-semibold text-default block mb-2">{m.audit_retention_period_label()}</label>
                  <div class="flex flex-col sm:flex-row items-start sm:items-center gap-2 mb-4">
                    <div class="flex items-center gap-2">
                      <Input.Text
                        bind:value={retentionInputValue}
                        type="number"
                        min="1"
                        max="2555"
                        class="w-20"
                        inputClass="text-center text-sm font-medium"
                      />
                      <span class="text-xs text-muted">
                        {m.audit_retention_days_unit()}
                      </span>
                    </div>
                    <div class="text-xs text-muted">
                      {retentionInputValue === 365 ? `(1 ${m.audit_retention_year()})` : retentionInputValue === 730 ? `(2 ${m.audit_retention_years()})` : retentionInputValue === 90 ? `(3 ${m.audit_retention_months()})` : retentionInputValue === 2555 ? `(7 ${m.audit_retention_years()})` : ''}
                    </div>
                  </div>
                  <div class="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
                    <Button
                      onclick={() => (retentionInputValue = 90)}
                      variant={retentionInputValue === 90 ? "primary" : "ghost"}
                      size="sm"
                      class="w-full text-sm font-medium"
                    >
                      3 mån
                    </Button>
                    <Button
                      onclick={() => (retentionInputValue = 365)}
                      variant={retentionInputValue === 365 ? "primary" : "ghost"}
                      size="sm"
                      class="w-full text-sm font-medium"
                    >
                      1 år
                    </Button>
                    <Button
                      onclick={() => (retentionInputValue = 730)}
                      variant={retentionInputValue === 730 ? "primary" : "ghost"}
                      size="sm"
                      class="w-full text-sm font-medium"
                    >
                      2 år
                    </Button>
                    <Button
                      onclick={() => (retentionInputValue = 2555)}
                      variant={retentionInputValue === 2555 ? "primary" : "ghost"}
                      size="sm"
                      class="w-full text-sm font-medium"
                    >
                      7 år
                    </Button>
                  </div>
                </div>
              </div>

              {#if retentionInputValue !== retentionDays}
                <div class={`rounded-lg p-2.5 text-xs transition-all border-l-4 ${
                  retentionInputValue < retentionDays
                    ? 'border-l-red-500 border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/50'
                    : 'border-l-blue-500 border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/50'
                }`}>
                  {#if retentionInputValue < retentionDays}
                    <div class="flex items-start gap-2.5">
                      <div class="rounded-full bg-red-100 dark:bg-red-900 p-1.5">
                        <IconInfo class="h-4 w-4 text-red-600 dark:text-red-400" />
                      </div>
                      <div class="flex-1 space-y-1">
                        <p class="font-semibold text-red-900 dark:text-red-200 text-xs">{m.audit_retention_warning_title()}</p>
                        <p class="text-red-800 dark:text-red-300 text-xs leading-[1.4]">
                          {m.audit_retention_warning_desc({ date: getRetentionCutoffDate(retentionInputValue) })}
                        </p>
                      </div>
                    </div>
                  {:else}
                    <div class="flex items-start gap-2.5">
                      <div class="rounded-full bg-blue-100 dark:bg-blue-900 p-1.5">
                        <IconInfo class="h-4 w-4 text-blue-600 dark:text-blue-400" />
                      </div>
                      <div class="flex-1 space-y-1">
                        <p class="font-semibold text-blue-900 dark:text-blue-200 text-xs">{m.audit_retention_info_title()}</p>
                        <p class="text-blue-800 dark:text-blue-300 text-xs leading-[1.4]">
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

              <div class="border-t border-default pt-3 mt-3">
                <p class="text-xs text-muted mb-2">
                  {m.audit_retention_range()}
                </p>
                <div class="flex items-center justify-end gap-2">
                  <Button onclick={cancelRetentionEdit} variant="ghost" disabled={isSavingRetention} class="min-w-[80px] text-sm font-medium">
                    {m.audit_retention_cancel()}
                  </Button>
                  <Button onclick={saveRetentionPolicy} variant="primary" disabled={isSavingRetention || retentionInputValue === retentionDays} class="min-w-[120px] text-sm font-medium">
                    {#if isSavingRetention}
                      <div class="flex items-center gap-2">
                        <div class="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent"></div>
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
          <div class="mb-6 flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-800 dark:bg-red-900/20">
            <IconInfo class="h-5 w-5 text-red-600 dark:text-red-400" />
            <p class="text-sm text-red-800 dark:text-red-200">{m.audit_error_loading()}</p>
            <Button onclick={() => window.location.reload()} variant="outlined" size="sm" class="ml-auto">
              {m.audit_retry()}
            </Button>
          </div>
        {/if}

        <!-- Filter Toolbar -->
        <div class="mb-4 rounded-lg border border-default bg-subtle p-4">
          <div class="flex flex-wrap items-center gap-3">
            <!-- Scoped Search (first, fills available space) -->
            <div class="scope-dropdown-container user-dropdown-container relative flex-1 min-w-[280px]">
              <!-- Scope trigger (inside input, left side) -->
              <div class="absolute left-2 top-1/2 -translate-y-1/2 z-10 flex items-center">
                <button
                  onclick={() => showScopeDropdown = !showScopeDropdown}
                  aria-haspopup="listbox"
                  aria-expanded={showScopeDropdown}
                  aria-label="Search scope: {searchScope === 'entity' ? 'Entity' : 'User'}"
                  class="flex items-center gap-1.5 h-7 px-2.5 text-xs font-semibold rounded-md transition-all duration-150
                    text-muted bg-subtle/80 border border-default/40
                    hover:bg-hover hover:text-default hover:border-default/60
                    focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:ring-offset-1"
                >
                  {searchScope === 'entity' ? m.audit_search_scope_entity() : m.audit_search_scope_user()}
                  <IconChevronDown class={`h-3 w-3 transition-transform duration-150 ${showScopeDropdown ? 'rotate-180' : ''}`} />
                </button>

                <!-- Scope Dropdown menu -->
                {#if showScopeDropdown}
                  <div
                    role="listbox"
                    aria-label="Select search scope"
                    class="absolute top-full left-0 mt-1.5 bg-primary border border-default rounded-lg shadow-lg z-30 min-w-[140px] py-1 overflow-hidden"
                    transition:slide={{ duration: 150 }}
                  >
                    <button
                      role="option"
                      aria-selected={searchScope === 'entity'}
                      onclick={() => handleScopeChange('entity')}
                      class="w-full px-3 py-2 text-left text-sm flex items-center justify-between gap-2 transition-colors
                        {searchScope === 'entity' ? 'font-medium text-accent-default bg-accent-default/5' : 'text-default hover:bg-subtle'}"
                    >
                      {m.audit_search_scope_entity()}
                      {#if searchScope === 'entity'}
                        <IconCheck class="h-4 w-4 text-accent-default" />
                      {/if}
                    </button>
                    <button
                      role="option"
                      aria-selected={searchScope === 'user'}
                      onclick={() => handleScopeChange('user')}
                      class="w-full px-3 py-2 text-left text-sm flex items-center justify-between gap-2 transition-colors
                        {searchScope === 'user' ? 'font-medium text-accent-default bg-accent-default/5' : 'text-default hover:bg-subtle'}"
                    >
                      {m.audit_search_scope_user()}
                      {#if searchScope === 'user'}
                        <IconCheck class="h-4 w-4 text-accent-default" />
                      {/if}
                    </button>
                  </div>
                {/if}

                <!-- Visual divider -->
                <div class="ml-2 h-6 w-px bg-default/40"></div>
              </div>

              <!-- Search input -->
              <input
                type="text"
                bind:value={searchQuery}
                oninput={(e) => handleScopedSearch(e.currentTarget.value)}
                onfocus={() => searchScope === 'user' && searchQuery.length >= 3 && userSearchResults.length > 0 && (showUserDropdown = true)}
                placeholder={searchScope === 'entity' ? m.audit_search_placeholder_entity() : m.audit_search_placeholder_user()}
                aria-label={searchScope === 'entity' ? 'Search by entity name' : 'Search by user email'}
                autocomplete="off"
                class="w-full h-11 pl-32 pr-10 rounded-lg border border-default bg-primary text-sm text-default placeholder:text-muted
                  focus:outline-none focus:ring-2 focus:ring-accent-default/30 focus:border-accent-default transition-all duration-150"
              />

              <!-- Clear button (right side) -->
              {#if searchQuery.length > 0}
                <button
                  onclick={clearSearch}
                  class="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1.5 transition-all duration-150
                    text-muted hover:text-default hover:bg-hover
                    focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-default"
                  aria-label={m.audit_search_clear()}
                >
                  <IconXMark class="h-4 w-4" />
                </button>
              {/if}

              <!-- Loading spinner for user search -->
              {#if isSearchingUsers && searchScope === 'user'}
                <div class="absolute right-8 top-1/2 -translate-y-1/2">
                  <div class="h-4 w-4 animate-spin rounded-full border-2 border-accent-default border-t-transparent"></div>
                </div>
              {/if}

              <!-- User dropdown results (only when scope = 'user') -->
              {#if searchScope === 'user' && showUserDropdown && userSearchResults.length > 0}
                <div
                  role="listbox"
                  aria-label="User search results"
                  class="absolute top-full left-0 right-0 mt-2 z-20 rounded-lg border border-default bg-primary shadow-xl max-h-64 overflow-y-auto"
                  transition:slide={{ duration: 150 }}
                >
                  {#each userSearchResults as user, index}
                    <button
                      role="option"
                      aria-selected={false}
                      onclick={() => selectUser(user)}
                      class="w-full px-4 py-3 text-left transition-colors focus:outline-none
                        hover:bg-accent-default/5 focus:bg-accent-default/5
                        {index > 0 ? 'border-t border-default/50' : ''}"
                    >
                      <div class="flex items-center gap-3">
                        <div class="flex h-8 w-8 items-center justify-center rounded-full bg-accent-default/10 text-accent-default text-xs font-semibold">
                          {user.email.charAt(0).toUpperCase()}
                        </div>
                        <span class="text-sm font-medium text-default">{user.email}</span>
                      </div>
                    </button>
                  {/each}
                </div>
              {/if}

              <!-- Empty state for user search (only shows after search completes with 0 results) -->
              {#if searchScope === 'user' && searchQuery.length >= 3 && userSearchCompleted && userSearchResults.length === 0}
                <div
                  class="absolute top-full left-0 right-0 mt-2 z-20 rounded-lg border border-default bg-primary shadow-lg p-4"
                  transition:fade={{ duration: 150 }}
                >
                  <div class="flex flex-col items-center gap-2 text-center py-2">
                    <div class="rounded-full bg-muted/20 p-2">
                      <IconXMark class="h-5 w-5 text-muted" />
                    </div>
                    <p class="text-sm text-muted">Inga användare hittades</p>
                    <p class="text-xs text-muted/70">Försök med en annan sökning</p>
                  </div>
                </div>
              {/if}
            </div>

            <!-- Filters Row (second) -->
            <div class="flex flex-wrap items-center gap-2 sm:gap-3 lg:gap-4">
              <Input.DateRange bind:value={dateRange} />

              <!-- Quick filter buttons (connected button group) -->
              <div class="flex items-center h-10 rounded-lg border border-default/60 overflow-hidden flex-shrink-0 bg-subtle/50" role="group" aria-label="Quick date presets">
                <button
                  onclick={() => setDatePreset(7)}
                  aria-pressed={activePreset === 7}
                  class={`px-4 py-2 text-xs font-semibold transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent-default ${
                    activePreset === 7
                      ? 'bg-accent-default text-white shadow-sm'
                      : 'text-muted hover:bg-hover hover:text-default active:scale-95'
                  }`}
                >
                  7d
                </button>
                <button
                  onclick={() => setDatePreset(30)}
                  aria-pressed={activePreset === 30}
                  class={`px-4 py-2 text-xs font-semibold border-x border-default/40 transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent-default ${
                    activePreset === 30
                      ? 'bg-accent-default text-white shadow-sm border-x-transparent'
                      : 'text-muted hover:bg-hover hover:text-default active:scale-95'
                  }`}
                >
                  30d
                </button>
                <button
                  onclick={() => setDatePreset(90)}
                  aria-pressed={activePreset === 90}
                  class={`px-4 py-2 text-xs font-semibold transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent-default ${
                    activePreset === 90
                      ? 'bg-accent-default text-white shadow-sm'
                      : 'text-muted hover:bg-hover hover:text-default active:scale-95'
                  }`}
                >
                  90d
                </button>
              </div>

              <!-- Action Multi-Select -->
              <div class="min-w-[200px] sm:min-w-[220px] relative">
                <Dropdown.Root bind:open={showActionDropdown} gutter={4} placement="bottom-start">
                  <Dropdown.Trigger asFragment let:trigger>
                    <Button
                      is={trigger}
                      variant="outline"
                      class="w-full justify-between"
                      aria-haspopup="listbox"
                      aria-expanded={showActionDropdown}
                      aria-label={selectedActions.length === 0
                        ? m.audit_all_actions()
                        : `${selectedActions.length} ${m.audit_actions_selected()}`}
                    >
                      <span class={selectedActions.length === 0 ? 'text-muted' : 'text-default'}>
                        {#if selectedActions.length === 0}
                          {m.audit_all_actions()}
                        {:else if selectedActions.length === 1}
                          {actionOptions.find(o => o.value === selectedActions[0])?.label}
                        {:else}
                          {selectedActions.length} {m.audit_actions_selected()}
                        {/if}
                      </span>
                      <IconChevronDown class={`h-4 w-4 text-muted transition-transform duration-200 ${showActionDropdown ? 'rotate-180' : ''}`} />
                    </Button>
                  </Dropdown.Trigger>
                  <Dropdown.Menu>
                    <!-- Scrollable container wrapper (Dropdown.Menu doesn't pass class prop) -->
                    <div
                      class="relative max-h-[50vh] sm:max-h-[300px] overflow-y-auto min-w-[280px] sm:min-w-[300px] overscroll-contain scroll-smooth -mx-2 -mb-2"
                      role="listbox"
                      aria-multiselectable="true"
                      aria-label={m.audit_all_actions()}
                    >
                      <!-- Selected count header when items are selected -->
                      {#if selectedActions.length > 0}
                        <div class="-mt-2 sticky top-0 z-20 flex items-center justify-between px-3 py-2.5 bg-primary border-b border-default text-xs font-medium shadow-sm">
                          <span class="text-muted">{selectedActions.length} {m.audit_actions_selected()}</span>
                          <button
                            class="px-2 py-1 rounded text-accent-default hover:text-white hover:bg-accent-default transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-default"
                            onclick={() => { selectedActions = []; applyFilters(); }}
                            aria-label="Clear all selected actions"
                          >
                            {m.audit_clear_all()}
                          </button>
                        </div>
                      {/if}

                      <!-- Items list with proper stacking context -->
                      <div class="relative z-10">
                        {#each actionOptions.filter(o => o.value !== 'all') as option, index}
                          {@const isSelected = selectedActions.includes(option.value as ActionType)}
                          <button
                            role="option"
                            aria-selected={isSelected}
                            tabindex={showActionDropdown ? 0 : -1}
                            class={`flex w-full items-center gap-3 px-3 py-2.5 sm:py-2 text-sm text-left transition-all duration-150 bg-primary
                              hover:bg-hover focus:bg-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent-default/50
                              ${isSelected ? 'bg-accent-default/5' : ''}`}
                          onclick={() => toggleAction(option.value as ActionType)}
                          onkeydown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault();
                              toggleAction(option.value as ActionType);
                            }
                          }}
                        >
                          <span
                            class={`flex h-5 w-5 sm:h-4 sm:w-4 shrink-0 items-center justify-center rounded border-2 transition-all duration-200 ${
                              isSelected
                                ? 'bg-accent-default border-accent-default scale-100 shadow-sm shadow-accent-default/25'
                                : 'border-default/60 hover:border-default scale-95 hover:scale-100'
                            }`}
                            aria-hidden="true"
                          >
                            {#if isSelected}
                              <IconCheck class="h-3 w-3 text-on-fill" />
                            {/if}
                          </span>
                          <span class={`flex-1 ${isSelected ? 'text-default font-medium' : 'text-default'}`}>
                            {option.label}
                          </span>
                          {#if isSelected}
                            <span class="sr-only">(selected)</span>
                          {/if}
                          </button>
                        {/each}
                      </div>

                      <!-- Scroll fade indicator at bottom -->
                      <div class="sticky bottom-0 h-4 bg-gradient-to-t from-primary to-transparent pointer-events-none z-10" aria-hidden="true"></div>
                    </div>
                  </Dropdown.Menu>
                </Dropdown.Root>
              </div>
            </div>
          </div>
        </div>

        <!-- Active Filter Chips (OUTSIDE toolbar) -->
        {#if activeFilterCount > 0}
          <div class="flex flex-wrap items-center gap-2 mb-4">
            {#if dateRange?.start && dateRange?.end && !activePreset}
              <span transition:scale={{ duration: 150, start: 0.9 }} class="inline-flex items-center gap-1.5 rounded-full bg-blue-50 dark:bg-blue-950 px-3 py-1 text-xs shadow-sm">
                <span class="text-blue-800 dark:text-blue-300">
                  {dateRange.start.toString()} – {dateRange.end.toString()}
                </span>
                <button
                  onclick={() => { dateRange = { start: undefined, end: undefined }; applyFilters(); }}
                  class="rounded-full hover:bg-blue-100 dark:hover:bg-blue-900 p-0.5 transition-all duration-150 hover:scale-110"
                >
                  <IconXMark class="h-3 w-3 text-blue-700 dark:text-blue-300" />
                </button>
              </span>
            {/if}

            {#each selectedActions as action}
              <span transition:scale={{ duration: 150, start: 0.9 }} class="inline-flex items-center gap-1.5 rounded-full bg-purple-50 dark:bg-purple-950 px-3 py-1 text-xs shadow-sm">
                <span class="text-purple-800 dark:text-purple-300">
                  {actionOptions.find(o => o.value === action)?.label}
                </span>
                <button
                  onclick={() => { selectedActions = selectedActions.filter(a => a !== action); applyFilters(); }}
                  class="rounded-full hover:bg-purple-100 dark:hover:bg-purple-900 p-0.5 transition-all duration-150 hover:scale-110"
                >
                  <IconXMark class="h-3 w-3 text-purple-700 dark:text-purple-300" />
                </button>
              </span>
            {/each}

            {#if selectedUser}
              <span transition:scale={{ duration: 150, start: 0.9 }} class="inline-flex items-center gap-1.5 rounded-full bg-green-50 dark:bg-green-950 px-3 py-1 text-xs shadow-sm">
                <span class="text-green-800 dark:text-green-300">
                  {m.audit_filtering_by_user()}: {selectedUser.email}
                </span>
                <button
                  onclick={clearUserFilter}
                  class="rounded-full hover:bg-green-100 dark:hover:bg-green-900 p-0.5 transition-all duration-150 hover:scale-110"
                >
                  <IconXMark class="h-3 w-3 text-green-700 dark:text-green-300" />
                </button>
              </span>
            {/if}

            {#if searchScope === 'entity' && searchQuery.length >= 3}
              <span transition:scale={{ duration: 150, start: 0.9 }} class="inline-flex items-center gap-1.5 rounded-full bg-amber-50 dark:bg-amber-950 px-3 py-1 text-xs shadow-sm">
                <span class="text-amber-800 dark:text-amber-300">
                  {m.audit_filtering_by_entity()}: "{searchQuery}"
                </span>
                <button
                  onclick={clearSearch}
                  class="rounded-full hover:bg-amber-100 dark:hover:bg-amber-900 p-0.5 transition-all duration-150 hover:scale-110"
                >
                  <IconXMark class="h-3 w-3 text-amber-700 dark:text-amber-300" />
                </button>
              </span>
            {/if}

            <!-- Clear all (ghost button with icon) - accessible hover with 4.5:1+ contrast -->
            <button
              onclick={clearFilters}
              class="ml-2 inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium rounded-md transition-all duration-150
                text-muted hover:text-white dark:hover:text-white
                hover:bg-red-600 dark:hover:bg-red-500
                focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2
                active:scale-95"
            >
              <Trash2 class="h-3.5 w-3.5" />
              {m.audit_clear_all()}
            </button>
          </div>
        {/if}

        <!-- Results Summary and Top Pagination -->
        <div class="mb-6 rounded-lg bg-subtle p-4">
          <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div class="flex items-center gap-3">
              <p class="text-sm font-medium text-default">
                {m.audit_showing_results({ shown: logs.length, total: totalCount })}
              </p>
              {#if totalPages > 1}
                <span class="text-sm text-muted border-l border-default pl-3">
                  {m.audit_page_info({ current: currentPage, total: totalPages })}
                </span>
              {/if}
            </div>

            {#if totalPages > 1}
              <div class="flex items-center gap-3">
                <Button onclick={prevPage} disabled={currentPage <= 1} variant="outlined" size="sm" class="min-w-[100px]">
                  {m.audit_previous()}
                </Button>
                <Button onclick={nextPage} disabled={currentPage >= totalPages} variant="outlined" size="sm" class="min-w-[100px]">
                  {m.audit_next()}
                </Button>
              </div>
            {/if}
          </div>
        </div>

        <!-- Audit Logs Table -->
        <div class="rounded-lg border border-default shadow-sm bg-primary">
          <div class="overflow-x-auto">
            <table class="w-full">
              <thead class="sticky top-0 border-b-2 border-accent-default/20 bg-subtle">
                <tr>
                  <th class="w-8 px-4 py-3"></th>
                  <th class="px-4 py-3 text-left text-xs font-semibold text-default uppercase tracking-wider w-[15%]">
                    {m.audit_timestamp()}
                  </th>
                  <th class="px-4 py-3 text-left text-xs font-semibold text-default uppercase tracking-wider w-[15%]">
                    {m.audit_action()}
                  </th>
                  <th class="px-4 py-3 text-left text-xs font-semibold text-default uppercase tracking-wider w-[45%]">
                    {m.audit_description()}
                  </th>
                  <th class="px-4 py-3 text-left text-xs font-semibold text-default uppercase tracking-wider w-[18%]">
                    {m.audit_actor()}
                  </th>
                  <th class="px-4 py-3 text-center text-xs font-semibold text-default uppercase tracking-wider w-[7%]">
                    {m.audit_status()}
                  </th>
                </tr>
              </thead>
              <tbody class="divide-y divide-default bg-primary">
                {#if logs.length === 0}
                  <tr>
                    <td colspan="6" class="px-4 py-16 text-center">
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
                  {#each logs as log, index (log.id || index)}
                    {@const isExpanded = expandedRows.has(log.id || index.toString())}
                    <!-- Main Row -->
                    <tr
                      class="cursor-pointer transition-colors duration-150 hover:bg-hover/70"
                      onclick={() => toggleRowExpansion(log.id || index.toString())}
                    >
                      <td class="px-4 py-3">
                        <div class="rounded-md hover:bg-hover p-1 transition-colors duration-150">
                          <IconChevronDown class={`h-5 w-5 text-muted transition-transform duration-200 ${isExpanded ? 'rotate-180' : ''}`} />
                        </div>
                      </td>
                      <td class="px-4 py-3">
                        <div class="flex flex-col">
                          <span class="text-sm font-medium text-default" title={formatFullTimestamp(log.timestamp)}>
                            {formatTimestamp(log.timestamp)}
                          </span>
                          <span class="text-xs text-muted">
                            {new Date(log.timestamp).toLocaleTimeString(getLocale())}
                          </span>
                        </div>
                      </td>
                      <td class="px-4 py-3">
                        <span class={`inline-flex rounded-md px-2.5 py-1 text-xs font-medium shadow-sm ${getActionBadgeClass(log.action)}`}>
                          {getActionLabel(log.action as ActionType)}
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
                        {#if log.outcome === "success"}
                          <span class="inline-flex items-center gap-1 rounded-md bg-green-50 dark:bg-green-950 px-2 py-1 text-xs font-medium text-green-900 dark:text-green-300 border border-green-200 dark:border-green-800 transition-transform duration-150 hover:scale-105">
                            <CircleCheck class="h-3.5 w-3.5" />
                            {m.audit_success()}
                          </span>
                        {:else}
                          <span class="inline-flex items-center gap-1 rounded-md bg-red-50 dark:bg-red-950 px-2 py-1 text-xs font-medium text-red-900 dark:text-red-300 border border-red-200 dark:border-red-800 transition-transform duration-150 hover:scale-105">
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
                            <h4 class="text-xs font-semibold text-default uppercase tracking-wider">{m.audit_full_details()}</h4>
                            <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                              <div class="rounded-lg border border-default bg-primary p-3">
                                <p class="text-xs font-medium text-muted mb-1">{m.audit_full_timestamp()}</p>
                                <p class="text-sm text-default">{formatFullTimestamp(log.timestamp)}</p>
                              </div>
                              <div class="rounded-lg border border-default bg-primary p-3">
                                <p class="text-xs font-medium text-muted mb-1">{m.audit_outcome()}</p>
                                <p class="text-sm text-default">{log.outcome === "success" ? m.audit_success() : m.audit_failure()}</p>
                              </div>
                            </div>
                            {#if log.metadata && Object.keys(log.metadata).length > 0}
                              <div class="rounded-lg border border-default bg-primary p-3">
                                <div class="flex items-center justify-between mb-2">
                                  <p class="text-xs font-medium text-muted">{m.audit_metadata_json()}</p>
                                  <button
                                    onclick={() => copyJsonToClipboard(log.metadata, log.id || index.toString())}
                                    class="flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium text-muted hover:bg-hover hover:text-default transition-all duration-150 hover:scale-105 active:scale-95"
                                    aria-label={m.audit_copy_json()}
                                  >
                                    {#if copiedRowId === (log.id || index.toString())}
                                      <IconCheck class="h-3.5 w-3.5 text-green-600 dark:text-green-400" />
                                      <span class="text-green-600 dark:text-green-400">{m.audit_json_copied()}</span>
                                    {:else}
                                      <IconCopy class="h-3.5 w-3.5" />
                                      {m.audit_copy_json()}
                                    {/if}
                                  </button>
                                </div>
                                <pre class="text-xs text-gray-800 dark:text-gray-200 rounded bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800 p-3 max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono">{@html formatJsonWithSyntaxHighlighting(log.metadata)}</pre>
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
          <div class="mt-8 rounded-lg bg-subtle p-4">
            <div class="flex items-center justify-center gap-4">
              <Button onclick={prevPage} disabled={currentPage <= 1} variant="outlined" class="min-w-[120px] transition-transform duration-150 hover:scale-[1.02] active:scale-[0.98]">
                {m.audit_previous()}
              </Button>
              <span class="text-sm px-4 py-2 rounded-md bg-primary border border-default">
                {m.audit_page()} <span class="font-semibold text-default">{currentPage}</span> {m.audit_of()} <span class="font-semibold text-default">{totalPages}</span>
              </span>
              <Button onclick={nextPage} disabled={currentPage >= totalPages} variant="outlined" class="min-w-[120px] transition-transform duration-150 hover:scale-[1.02] active:scale-[0.98]">
                {m.audit_next()}
              </Button>
            </div>
          </div>
        {/if}
        </div> <!-- End of logs tab container -->
        {/if} <!-- End of justification check -->
      {:else if activeTab === 'config'}
        <!-- Configuration Tab Content -->
        <div class="px-4 pb-8 sm:px-6 lg:px-8">
          <AuditConfigTab />
        </div>
      {/if}
  </Page.Main>
</Page.Root>