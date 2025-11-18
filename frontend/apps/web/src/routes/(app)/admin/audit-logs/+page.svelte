<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { writable } from "svelte/store";
  import { Page } from "$lib/components/layout";
  import { Button, Input, Select, Dropdown } from "@intric/ui";
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
  import { Clock, CircleCheck, CircleX, Calendar, Shield, FileText, Settings } from "lucide-svelte";
  import { slide, fade } from "svelte/transition";
  import { getIntric } from "$lib/core/Intric";
  import { getLocale } from "$lib/paraglide/runtime";
  import { onMount } from "svelte";
  import AuditConfigTab from "./AuditConfigTab.svelte";
  import AccessJustificationForm from "./AccessJustificationForm.svelte";

  type AuditLogResponse = components["schemas"]["AuditLogResponse"];
  type ActionType = components["schemas"]["ActionType"];

  let { data } = $props();

  const intric = getIntric();

  // Access justification state (initialized from server data to prevent flash)
  let accessJustification = $state<{ category: string; description: string; timestamp: string } | null>(data.justification);
  let hasProvidedJustification = $derived(accessJustification !== null);

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

  // Sync justification state when data changes (e.g., navigation)
  $effect(() => {
    accessJustification = data.justification;
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
    // Store justification with timestamp
    accessJustification = {
      ...justification,
      timestamp: new Date().toISOString()
    };

    // Reload the page data with justification params
    const params = new URLSearchParams($page.url.search);
    params.set('justification_category', justification.category);
    params.set('justification_description', justification.description);

    await goto(`/admin/audit-logs?${params.toString()}`, { invalidateAll: true });
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
  let selectedUser = $state<UserSparse | null>(null);
  let userSearchQuery = $state("");
  let userSearchResults = $state<UserSparse[]>([]);
  let isSearchingUsers = $state(false);
  let showUserDropdown = $state(false);
  let debounceTimer: ReturnType<typeof setTimeout>;
  let userSearchTimer: ReturnType<typeof setTimeout>;
  let isExporting = $state(false);

  // Retention policy state
  let retentionDays = $state<number>(365);
  let isEditingRetention = $state(false);
  let retentionInputValue = $state<number>(365);
  let isSavingRetention = $state(false);
  let retentionError = $state<string | null>(null);

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
  ]);

  // Create store for Select component
  const actionStore = writable<{ value: ActionType | "all"; label: string }>({
    value: "all",
    label: m.audit_all_actions()
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
        // Subtract 1 day from end date when reading from URL
        // (We add 1 day in applyFilters to make it inclusive)
        const endDateFromUrl = parseDate(toDate).subtract({ days: 1 });
        dateRange = {
          start: parseDate(fromDate),
          end: endDateFromUrl
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
      actionStore.set({ value: "all", label: m.audit_all_actions() });
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
    const endDate = today(tz); // Set to current day (applyFilters will add 1 day to make it inclusive)
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

  function applyFilters() {
    const params = new URLSearchParams();

    if (data.page) params.set("page", data.page.toString());
    if (data.page_size) params.set("page_size", data.page_size.toString());

    if (dateRange?.start && dateRange?.end) {
      params.set("from_date", dateRange.start.toString());
      // Add 1 day to end date to make it inclusive (include full selected day)
      const inclusiveEndDate = dateRange.end.add({ days: 1 });
      params.set("to_date", inclusiveEndDate.toString());
    }

    if (selectedAction !== "all") {
      params.set("action", selectedAction);
    }

    if (selectedUser) {
      params.set("actor_id", selectedUser.id);
    }

    // Preserve justification params (required for compliance tracking)
    if (accessJustification) {
      params.set("justification_category", accessJustification.category);
      params.set("justification_description", accessJustification.description);
    }

    if (activeTab === 'config') {
      params.set("tab", "config");
    }

    const url = params.toString() ? `/admin/audit-logs?${params.toString()}` : "/admin/audit-logs";
    goto(url, { noScroll: true, keepFocus: true });
  }

  function clearFilters() {
    dateRange = { start: undefined, end: undefined };
    selectedAction = "all";
    actionStore.set({ value: "all", label: m.audit_all_actions() });
    selectedUser = null;
    userSearchQuery = "";
    userSearchResults = [];

    const params = new URLSearchParams();
    if (activeTab === 'config') {
      params.set("tab", "config");
    }

    const url = params.toString() ? `/admin/audit-logs?${params.toString()}` : "/admin/audit-logs";
    goto(url, { noScroll: true });
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

  async function exportLogs(format: "csv" | "json") {
    try {
      isExporting = true;
      const params = new URLSearchParams($page.url.search);
      params.set("format", format);

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
      const extension = format === "json" ? "jsonl" : "csv";
      const filename = `audit_logs_${dateStr}.${extension}`;

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

  // Auto-apply filters on any filter change (consolidated for performance)
  $effect(() => {
    // Track filter changes and apply with debounce
    const hasDateFilter = dateRange?.start && dateRange?.end;
    const hasActionFilter = selectedAction !== undefined && selectedAction !== "all";

    // Only auto-apply if we're not in the initial load state
    if (hasDateFilter || hasActionFilter) {
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

  // Retention policy functions
  async function fetchRetentionPolicy() {
    try {
      const policy = await intric.audit.getRetentionPolicy();
      retentionDays = policy.retention_days;
      retentionInputValue = policy.retention_days;
    } catch (err) {
      console.error("Failed to fetch retention policy:", err);
    }
  }

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

  // Load retention policy on mount
  onMount(() => {
    fetchRetentionPolicy();
  });
</script>

<svelte:head>
  <title>Eneo.ai – Admin – Audit Logs</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <div class="flex items-center gap-4">
      <Page.Title title={m.audit_logs()}></Page.Title>
    </div>
    {#if activeTab === 'logs' && hasProvidedJustification}
      <div class="flex gap-[1px]">
        <Button variant="primary" onclick={() => exportLogs("csv")} disabled={isExporting} class="!rounded-r-none">
          {#if isExporting}
            <div class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></div>
            {m.audit_exporting()}
          {:else}
            <IconDownload class="h-4 w-4" />
            Export ({data.total_count})
          {/if}
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
  </Page.Header>

  <Page.Main>
    {#if !(activeTab === 'logs' && !hasProvidedJustification)}
    <!-- Description with better spacing and visual treatment -->
    <div class="mb-6 px-4 sm:px-6 lg:px-8">
      <p class="text-sm text-muted leading-relaxed">
        {m.audit_logs_description()}
      </p>
    </div>

    <!-- Tabs with improved styling -->
    <div class="mb-6 px-4 sm:px-6 lg:px-8">
      <div class="inline-flex gap-1 p-1.5 bg-subtle rounded-lg border border-default shadow-sm">
        <button
          onclick={() => switchTab('logs')}
          class={`flex items-center justify-center gap-2 px-6 py-2.5 rounded-md text-sm font-semibold transition-all ${
            activeTab === 'logs'
              ? 'bg-accent-default text-on-fill shadow-md ring-1 ring-accent-default/20'
              : 'text-muted hover:text-default hover:bg-hover'
          }`}
        >
          <FileText class="h-4 w-4" />
          {m.audit_tab_logs()}
        </button>
        <button
          onclick={() => switchTab('config')}
          class={`flex items-center justify-center gap-2 px-6 py-2.5 rounded-md text-sm font-semibold transition-all ${
            activeTab === 'config'
              ? 'bg-accent-default text-on-fill shadow-md ring-1 ring-accent-default/20'
              : 'text-muted hover:text-default hover:bg-hover'
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
        {#if !hasProvidedJustification}
          <!-- Access Justification Form -->
          <AccessJustificationForm onSubmit={handleJustificationSubmit} />
        {:else}
        <div class="px-4 sm:px-6 lg:px-8">
        <!-- Retention Policy Section -->
        <div class="mb-8 rounded-xl border border-default bg-subtle p-5">
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
            <div class="rounded-lg bg-primary p-4 space-y-2">
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
            <div class="space-y-3">
              <div class="rounded-lg bg-primary p-4 space-y-3">
                <div class="max-w-xl">
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

        <!-- Filters Section -->
        <div class="mb-6 rounded-lg border border-default bg-subtle p-6">
          <div class="space-y-4">
            <!-- Header Row -->
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-sm font-semibold text-default">{m.audit_filters()}</h3>
              {#if activeFilterCount > 0}
                <button
                  onclick={clearFilters}
                  class="flex items-center gap-1.5 rounded-md bg-red-50 dark:bg-red-950 px-3 py-1.5 text-xs font-medium text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800 hover:bg-red-100 dark:hover:bg-red-900 transition-colors"
                >
                  <IconXMark class="h-3.5 w-3.5" />
                  {m.audit_clear_filter({ count: activeFilterCount })}
                </button>
              {/if}
            </div>

            <!-- Quick Filters Row -->
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs font-medium text-muted">{m.audit_quick_range()}</span>
              <button
                onclick={() => setDatePreset(7)}
                class="inline-flex items-center gap-1.5 rounded-md border border-default px-3 py-1.5 text-xs font-medium text-default hover:bg-subtle transition-colors"
              >
                <Clock class="h-3.5 w-3.5" />
                {m.audit_last_7_days()}
              </button>
              <button
                onclick={() => setDatePreset(30)}
                class="inline-flex items-center gap-1.5 rounded-md border border-default px-3 py-1.5 text-xs font-medium text-default hover:bg-subtle transition-colors"
              >
                <Clock class="h-3.5 w-3.5" />
                {m.audit_last_30_days()}
              </button>
              <button
                onclick={() => setDatePreset(90)}
                class="inline-flex items-center gap-1.5 rounded-md border border-default px-3 py-1.5 text-xs font-medium text-default hover:bg-subtle transition-colors"
              >
                <Clock class="h-3.5 w-3.5" />
                {m.audit_last_90_days()}
              </button>
            </div>

            <!-- Filter Grid -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
              <!-- Date Range Filter -->
              <div>
                <label class="block text-xs font-medium text-default mb-1.5">{m.audit_date_range()}</label>
                <div class="h-10">
                  <Input.DateRange bind:value={dateRange} class="w-full h-full" />
                </div>
              </div>

              <!-- Action Type Filter -->
              <div>
                <label class="block text-xs font-medium text-default mb-1.5">{m.audit_action_type()}</label>
                <Select.Root customStore={actionStore}>
                  <Select.Trigger class="w-full h-10 text-sm" placeholder="Select action type" />
                  <Select.Options>
                    {#each actionOptions as option}
                      <Select.Item value={option.value} label={option.label} />
                    {/each}
                  </Select.Options>
                </Select.Root>
              </div>

              <!-- User Filter -->
              <div>
                <label class="block text-xs font-medium text-default mb-1.5">{m.audit_user_filter()}</label>
                <div class="relative h-10">
                  <Input.Text
                    bind:value={userSearchQuery}
                    oninput={(e) => searchUsers(e.currentTarget.value)}
                    onfocus={() => userSearchQuery.length >= 3 && userSearchResults.length > 0 && (showUserDropdown = true)}
                    placeholder={m.audit_user_filter_placeholder()}
                    class="w-full h-10"
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

                  <!-- Dropdown Results -->
                  {#if showUserDropdown && userSearchResults.length > 0}
                    <div
                      class="absolute top-full left-0 right-0 mt-2 z-20 rounded-lg border border-default bg-primary shadow-xl max-h-64 overflow-y-auto divide-y divide-default"
                      transition:fade={{ duration: 150 }}
                    >
                      {#each userSearchResults as user}
                        <button
                          onclick={() => selectUser(user)}
                          class="w-full px-4 py-3 text-left hover:bg-subtle active:bg-subtle transition-colors focus:outline-none focus:bg-subtle"
                        >
                          <div class="flex flex-col gap-0.5">
                            <span class="text-sm font-medium text-default">{user.email}</span>
                            {#if user.name}
                              <span class="text-xs text-muted">{user.name}</span>
                            {/if}
                          </div>
                        </button>
                      {/each}
                    </div>
                  {/if}
                </div>
              </div>
            </div>

            <!-- Selected User Chip -->
            {#if selectedUser}
              <div class="flex items-center gap-2">
                <div class="inline-flex items-center gap-2 rounded-full bg-blue-50 dark:bg-blue-950 px-3 py-1 text-sm">
                  <span class="text-blue-900 dark:text-blue-300">
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
        </div>

        <!-- Results Summary and Top Pagination -->
        <div class="mb-6 rounded-lg bg-subtle p-4">
          <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div class="flex items-center gap-3">
              <p class="text-sm font-medium text-default">
                {m.audit_showing_results({ shown: data.logs.length, total: data.total_count })}
              </p>
              {#if data.total_pages > 1}
                <span class="text-sm text-muted border-l border-default pl-3">
                  {m.audit_page_info({ current: data.page, total: data.total_pages })}
                </span>
              {/if}
            </div>

            {#if data.total_pages > 1}
              <div class="flex items-center gap-3">
                <Button onclick={prevPage} disabled={data.page <= 1} variant="outlined" size="sm" class="min-w-[100px]">
                  {m.audit_previous()}
                </Button>
                <Button onclick={nextPage} disabled={data.page >= data.total_pages} variant="outlined" size="sm" class="min-w-[100px]">
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
              <thead class="sticky top-0 border-b border-default bg-subtle">
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
                {#if data.logs.length === 0}
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
                  {#each data.logs as log, index (log.id || index)}
                    {@const isExpanded = expandedRows.has(log.id || index.toString())}
                    <!-- Main Row -->
                    <tr
                      class="cursor-pointer transition-colors hover:bg-hover"
                      onclick={() => toggleRowExpansion(log.id || index.toString())}
                    >
                      <td class="px-4 py-3">
                        <div class="rounded-md hover:bg-hover p-1 transition-colors">
                          {#if isExpanded}
                            <IconChevronDown class="h-5 w-5 text-muted rotate-180 transition-transform" />
                          {:else}
                            <IconChevronDown class="h-5 w-5 text-muted transition-transform" />
                          {/if}
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
                        <span class={`inline-flex rounded-md px-2.5 py-1 text-xs font-medium ${getActionBadgeClass(log.action)}`}>
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
                          <span class="inline-flex items-center gap-1 rounded-md bg-green-50 dark:bg-green-950 px-2 py-1 text-xs font-medium text-green-900 dark:text-green-300 border border-green-200 dark:border-green-800">
                            <CircleCheck class="h-3.5 w-3.5" />
                            {m.audit_success()}
                          </span>
                        {:else}
                          <span class="inline-flex items-center gap-1 rounded-md bg-red-50 dark:bg-red-950 px-2 py-1 text-xs font-medium text-red-900 dark:text-red-300 border border-red-200 dark:border-red-800">
                            <CircleX class="h-3.5 w-3.5" />
                            {m.audit_failure()}
                          </span>
                        {/if}
                      </td>
                    </tr>

                    <!-- Expanded Metadata Row -->
                    {#if isExpanded}
                      <tr transition:fade={{ duration: 150 }}>
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
                                    class="flex items-center gap-1.5 rounded px-2 py-1 text-xs font-medium text-muted hover:bg-hover hover:text-default transition-colors"
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
        {#if data.total_pages > 1}
          <div class="mt-8 rounded-lg bg-subtle p-4">
            <div class="flex items-center justify-center gap-4">
              <Button onclick={prevPage} disabled={data.page <= 1} variant="outlined" class="min-w-[120px]">
                {m.audit_previous()}
              </Button>
              <span class="text-sm px-4 py-2 rounded-md bg-primary border border-default">
                {m.audit_page()} <span class="font-semibold text-default">{data.page}</span> {m.audit_of()} <span class="font-semibold text-default">{data.total_pages}</span>
              </span>
              <Button onclick={nextPage} disabled={data.page >= data.total_pages} variant="outlined" class="min-w-[120px]">
                {m.audit_next()}
              </Button>
            </div>
          </div>
        {/if}
        </div> <!-- End of logs tab container -->
        {/if} <!-- End of justification check -->
      {:else if activeTab === 'config'}
        <!-- Configuration Tab Content -->
        <div class="px-4 sm:px-6 lg:px-8">
          <AuditConfigTab />
        </div>
      {/if}
  </Page.Main>
</Page.Root>