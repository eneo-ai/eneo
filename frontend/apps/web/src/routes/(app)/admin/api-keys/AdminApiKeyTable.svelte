<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import {
    ChevronDown,
    Key,
    Globe,
    Server,
    Building2,
    MessageSquare,
    AppWindow,
    Clock,
    Calendar,
    Activity,
    Shield,
    Lock,
    User,
    Eye,
    Pencil,
    ShieldCheck,
    Link,
    AlertTriangle
  } from "lucide-svelte";
  import { slide } from "svelte/transition";

  type ApiKeyUsageEvent = {
    id: string;
    timestamp: string;
    action: string;
    outcome: string;
    ip_address?: string | null;
    user_agent?: string | null;
    request_id?: string | null;
    request_path?: string | null;
    method?: string | null;
    origin?: string | null;
    error_message?: string | null;
  };

  type ApiKeyUsageResponse = {
    summary?: {
      total_events: number;
      used_events: number;
      auth_failed_events: number;
      last_seen_at?: string | null;
      last_success_at?: string | null;
      last_failure_at?: string | null;
      sampled_used_events?: boolean;
    };
    items?: ApiKeyUsageEvent[];
    limit?: number;
    next_cursor?: string | null;
  };

  type AdminApiKey = ApiKeyV2 & {
    owner_user?: { id: string; email?: string | null; username?: string | null } | null;
    created_by_user?: { id: string; email?: string | null; username?: string | null } | null;
    search_match_reasons?: string[] | null;
  };

  const intric = getIntric();
  import AdminApiKeyActions from "./AdminApiKeyActions.svelte";

  let {
    keys = [],
    loading = false,
    scopeNames = {},
    onChanged,
    onSecret
  } = $props<{
    keys: AdminApiKey[];
    loading: boolean;
    scopeNames?: Record<string, string>;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
  }>();

  // Track expanded rows
  let expandedIds = $state<Set<string>>(new Set());
  let activeTabByKey = $state<Record<string, "overview" | "usage">>({});
  let usageByKey = $state<Record<string, ApiKeyUsageResponse>>({});
  let usageErrorByKey = $state<Record<string, string | null>>({});
  let usageLoadingByKey = $state<Record<string, boolean>>({});
  let usageCursorByKey = $state<Record<string, string | null>>({});

  function toggleExpanded(id: string) {
    if (expandedIds.has(id)) {
      expandedIds.delete(id);
    } else {
      expandedIds.add(id);
    }
    expandedIds = new Set(expandedIds);
    if (expandedIds.has(id) && !activeTabByKey[id]) {
      activeTabByKey = { ...activeTabByKey, [id]: "overview" };
    }
  }

  function isActionClickTarget(target: EventTarget | null): boolean {
    return target instanceof Element && target.closest("[data-row-action]") !== null;
  }

  function handleRowClick(id: string, event: MouseEvent) {
    if (isActionClickTarget(event.target)) {
      return;
    }
    toggleExpanded(id);
  }

  function handleRowKeydown(id: string, event: KeyboardEvent) {
    if (isActionClickTarget(event.target)) {
      return;
    }
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      toggleExpanded(id);
    }
  }

  function getIdentityLabel(
    user: { email?: string | null; username?: string | null } | null | undefined,
    fallbackId: string | null | undefined
  ): string {
    if (user?.username) return user.username;
    if (user?.email) return user.email;
    if (!fallbackId) return "—";
    return `${fallbackId.slice(0, 8)}…`;
  }

  function getMatchReasonLabel(reason: string): string {
    switch (reason) {
      case "exact_secret":
        return m.api_keys_admin_match_reason_exact_secret();
      case "key_suffix":
        return m.api_keys_admin_match_reason_key_suffix();
      case "owner":
        return m.api_keys_admin_match_reason_owner();
      case "creator":
        return m.api_keys_admin_match_reason_creator();
      default:
        return m.api_keys_admin_match_reason_text();
    }
  }

  function setActiveTab(id: string, tab: "overview" | "usage") {
    activeTabByKey = { ...activeTabByKey, [id]: tab };
    if (tab === "usage") {
      void loadUsage(id, { reset: false });
    }
  }

  async function loadUsage(id: string, { reset }: { reset: boolean }) {
    if (usageLoadingByKey[id]) {
      return;
    }
    if (!reset && usageByKey[id]) {
      return;
    }

    usageLoadingByKey = { ...usageLoadingByKey, [id]: true };
    usageErrorByKey = { ...usageErrorByKey, [id]: null };
    try {
      const response = (await intric.apiKeys.admin.getUsage({
        id,
        limit: 25
      })) as ApiKeyUsageResponse;
      usageByKey = { ...usageByKey, [id]: response };
      usageCursorByKey = { ...usageCursorByKey, [id]: response?.next_cursor ?? null };
    } catch (error) {
      console.error(error);
      usageErrorByKey = {
        ...usageErrorByKey,
        [id]: error?.getReadableMessage?.() ?? m.something_went_wrong()
      };
    } finally {
      usageLoadingByKey = { ...usageLoadingByKey, [id]: false };
    }
  }

  async function loadMoreUsage(id: string) {
    const cursor = usageCursorByKey[id];
    if (!cursor || usageLoadingByKey[id]) {
      return;
    }
    usageLoadingByKey = { ...usageLoadingByKey, [id]: true };
    usageErrorByKey = { ...usageErrorByKey, [id]: null };
    try {
      const response = (await intric.apiKeys.admin.getUsage({
        id,
        limit: 25,
        cursor
      })) as ApiKeyUsageResponse;
      const existing = usageByKey[id];
      usageByKey = {
        ...usageByKey,
        [id]: {
          ...response,
          summary: existing?.summary ?? response.summary,
          items: [...(existing?.items ?? []), ...(response?.items ?? [])]
        }
      };
      usageCursorByKey = { ...usageCursorByKey, [id]: response?.next_cursor ?? null };
    } catch (error) {
      console.error(error);
      usageErrorByKey = {
        ...usageErrorByKey,
        [id]: error?.getReadableMessage?.() ?? m.something_went_wrong()
      };
    } finally {
      usageLoadingByKey = { ...usageLoadingByKey, [id]: false };
    }
  }

  const currentLocale = $derived.by(() => getLocale());
  const formatter = $derived.by(
    () =>
      new Intl.DateTimeFormat(currentLocale === "sv" ? "sv-SE" : "en-US", {
        dateStyle: "medium",
        timeStyle: "short"
      })
  );
  const relativeFormatter = $derived.by(
    () => new Intl.RelativeTimeFormat(currentLocale === "sv" ? "sv" : "en", { numeric: "auto" })
  );
  const fullNumberFormatter = $derived.by(
    () => new Intl.NumberFormat(currentLocale === "sv" ? "sv-SE" : "en-US")
  );
  const compactNumberFormatter = $derived.by(
    () =>
      new Intl.NumberFormat(currentLocale === "sv" ? "sv-SE" : "en-US", {
        notation: "compact",
        compactDisplay: "short",
        maximumFractionDigits: 1
      })
  );

  function formatUsageMetric(value: number | null | undefined): string {
    return compactNumberFormatter.format(value ?? 0);
  }

  function formatRelativeDate(date: string | null | undefined): string {
    if (!date) return m.api_keys_never();
    const d = new Date(date);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return m.api_keys_today();
    if (diffDays === 1) return m.api_keys_yesterday();
    if (diffDays < 7) return relativeFormatter.format(-diffDays, "day");
    if (diffDays < 30) return relativeFormatter.format(-Math.floor(diffDays / 7), "week");
    return formatter.format(d);
  }

  function getDaysUntilExpiration(date: string | null | undefined): number | null {
    if (!date) return null;
    const d = new Date(date);
    const now = new Date();
    return Math.ceil((d.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  }

  // Scope display helpers
  const scopeConfig = $derived<
    Record<string, { label: string; icon: typeof Building2; color: string }>
  >({
    tenant: {
      label: m.api_keys_admin_scope_tenant(),
      icon: Building2,
      color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300"
    },
    space: {
      label: m.api_keys_admin_scope_space(),
      icon: Building2,
      color: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300"
    },
    assistant: {
      label: m.api_keys_admin_scope_assistant(),
      icon: MessageSquare,
      color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300"
    },
    app: {
      label: m.api_keys_admin_scope_app(),
      icon: AppWindow,
      color: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300"
    }
  });

  const stateConfig = $derived<
    Record<string, { label: string; color: Label.LabelColor; dotColor: string }>
  >({
    active: { label: m.api_keys_admin_state_active(), color: "green", dotColor: "bg-green-500" },
    suspended: {
      label: m.api_keys_admin_state_suspended(),
      color: "yellow",
      dotColor: "bg-yellow-500"
    },
    revoked: { label: m.api_keys_admin_state_revoked(), color: "gray", dotColor: "bg-red-500" },
    expired: { label: m.api_keys_admin_state_expired(), color: "gray", dotColor: "bg-gray-500" }
  });

  const permissionConfig: Record<string, { label: string; color: string; icon: typeof Eye }> = {
    read: {
      label: m.api_keys_permission_read(),
      color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
      icon: Eye
    },
    write: {
      label: m.api_keys_permission_write(),
      color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
      icon: Pencil
    },
    admin: {
      label: m.api_keys_permission_admin(),
      color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
      icon: ShieldCheck
    }
  };

  function getKeyTypeConfig(keyType: string) {
    return keyType === "pk_"
      ? {
          label: m.api_keys_admin_key_type_public_label(),
          icon: Globe,
          color: "text-orange-600 dark:text-orange-400",
          bgColor: "bg-orange-100 dark:bg-orange-900/30"
        }
      : {
          label: m.api_keys_admin_key_type_secret_label(),
          icon: Lock,
          color: "text-blue-600 dark:text-blue-400",
          bgColor: "bg-blue-100 dark:bg-blue-900/30"
        };
  }

  function openAuditLogsForKey(key: AdminApiKey): string {
    const params = new URLSearchParams();
    params.set("tab", "logs");
    params.set("search", key.key_suffix);
    params.set("actions", "api_key_used,api_key_auth_failed");
    return `/admin/audit-logs?${params.toString()}`;
  }
</script>

{#if loading}
  <!-- Skeleton loader -->
  <div class="animate-pulse space-y-3">
    {#each Array(5) as _}
      <div class="border-default bg-primary rounded-xl border p-4">
        <div class="flex items-center gap-4">
          <div class="bg-subtle h-10 w-10 rounded-lg"></div>
          <div class="flex-1 space-y-2">
            <div class="bg-subtle h-4 w-40 rounded"></div>
            <div class="bg-subtle h-3 w-28 rounded"></div>
          </div>
          <div class="bg-subtle h-6 w-16 rounded"></div>
        </div>
      </div>
    {/each}
  </div>
{:else if keys.length === 0}
  <!-- Empty state -->
  <div class="border-default bg-subtle/50 rounded-xl border border-dashed p-12 text-center">
    <div
      class="bg-accent-default/10 mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl"
    >
      <Key class="text-accent-default h-8 w-8" />
    </div>
    <h3 class="text-default text-lg font-semibold">{m.api_keys_admin_no_keys_found()}</h3>
    <p class="text-muted mx-auto mt-2 max-w-md text-sm">
      {m.api_keys_admin_no_keys_match()}
    </p>
  </div>
{:else}
  <!-- Key list -->
  <div class="space-y-3">
    {#each keys as key (key.id)}
      {@const isExpanded = expandedIds.has(key.id)}
      {@const scope = scopeConfig[key.scope_type] ?? scopeConfig.tenant}
      {@const state = stateConfig[key.state] ?? stateConfig.active}
      {@const permission = permissionConfig[key.permission] ?? permissionConfig.read}
      {@const keyTypeConf = getKeyTypeConfig(key.key_type)}
      {@const daysUntil = getDaysUntilExpiration(key.expires_at)}
      {@const KeyTypeIcon = keyTypeConf.icon}
      {@const ScopeIcon = scope.icon}
      {@const PermissionIcon = permission.icon}

      <div
        class="group border-default bg-primary hover:border-dimmer overflow-hidden rounded-xl border transition-all
               duration-200 hover:shadow-md
               {isExpanded ? 'ring-accent-default/20 border-accent-default/30 ring-2' : ''}"
      >
        <!-- Main row -->
        <div
          role="button"
          tabindex="0"
          onclick={(event) => handleRowClick(key.id, event)}
          onkeydown={(event) => handleRowKeydown(key.id, event)}
          aria-expanded={isExpanded}
          aria-controls={"admin-api-key-details-" + key.id}
          class="focus-visible:ring-accent-default w-full cursor-pointer px-5 py-4 text-left focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          <div class="flex items-center gap-4">
            <!-- Key type icon -->
            <div
              class="flex h-11 w-11 items-center justify-center rounded-xl {keyTypeConf.bgColor}"
            >
              <KeyTypeIcon class="h-5 w-5 {keyTypeConf.color}" />
            </div>

            <!-- Key info -->
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-3">
                <h4 class="text-default truncate font-semibold">{key.name}</h4>

                <!-- Status dot and badge -->
                <div class="flex items-center gap-1.5">
                  <span class="h-2 w-2 rounded-full {state.dotColor}"></span>
                  <span class="text-muted text-xs">{state.label}</span>
                </div>
              </div>

              <!-- Key preview -->
              <div class="mt-1 flex flex-wrap items-center gap-3 text-sm">
                <code class="text-muted font-mono">
                  {key.key_type}<span class="text-default/40">•••</span>{key.key_suffix}
                </code>

                <!-- Scope badge -->
                <span
                  class="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium {scope.color}"
                >
                  <ScopeIcon class="h-3 w-3" />
                  {scope.label}
                  {#if key.scope_id}
                    <span class="opacity-60"
                      >· {scopeNames[key.scope_id] ?? key.scope_id.slice(0, 8)}</span
                    >
                  {/if}
                </span>

                <!-- Permission badge -->
                <span
                  class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold uppercase {permission.color}"
                >
                  <PermissionIcon class="h-3 w-3" />
                  {permission.label}
                </span>

                <!-- Key type badge -->
                <span
                  class="border-default bg-primary text-muted inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium"
                >
                  <KeyTypeIcon class="h-3 w-3" />
                  {keyTypeConf.label}
                </span>
              </div>

              <div class="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span class="text-muted inline-flex items-center gap-1.5">
                  <User class="h-3.5 w-3.5" />
                  {m.api_keys_admin_owner_label()}:
                  <span class="text-default font-medium">
                    {getIdentityLabel(key.owner_user, key.owner_user_id)}
                  </span>
                </span>
                {#if key.search_match_reasons?.length}
                  {#each key.search_match_reasons as reason}
                    <span
                      class="bg-accent-default/10 text-accent-default rounded px-1.5 py-0.5 text-[11px] font-medium"
                    >
                      {getMatchReasonLabel(reason)}
                    </span>
                  {/each}
                {/if}
              </div>
            </div>

            <!-- Right side info -->
            <div class="hidden items-center text-sm lg:flex">
              <!-- Rate limit -->
              <div class="border-default/50 border-l px-4 text-right first:border-l-0 first:pl-0">
                <p class="text-muted text-xs">{m.api_keys_admin_rate_limit()}</p>
                <p class="text-default font-medium">
                  {key.rate_limit ? `${key.rate_limit}/hr` : m.api_keys_default()}
                </p>
              </div>

              <!-- Expiration -->
              {#if daysUntil !== null}
                <div class="border-default/50 border-l px-4 text-right first:border-l-0 first:pl-0">
                  <p class="text-muted text-xs">{m.api_keys_expires()}</p>
                  <p
                    class="font-medium {daysUntil <= 7
                      ? 'text-yellow-600 dark:text-yellow-400'
                      : daysUntil <= 0
                        ? 'text-red-600 dark:text-red-400'
                        : 'text-default'}"
                  >
                    {daysUntil <= 0
                      ? m.api_keys_admin_expired_label()
                      : daysUntil === 1
                        ? m.api_keys_tomorrow()
                        : m.api_keys_days({ count: daysUntil })}
                  </p>
                </div>
              {/if}

              <!-- Last used -->
              <div class="border-default/50 border-l pl-4 text-right first:border-l-0 first:pl-0">
                <p class="text-muted text-xs">{m.api_keys_last_used()}</p>
                <p class="text-default font-medium">{formatRelativeDate(key.last_used_at)}</p>
              </div>
            </div>

            <!-- Actions and expand -->
            <div class="flex items-center gap-2">
              <div data-row-action>
                <AdminApiKeyActions apiKey={key} {onChanged} {onSecret} />
              </div>

              <div
                class="text-muted group-hover:bg-subtle flex h-8 w-8 items-center justify-center
                       rounded-lg transition-colors"
              >
                <ChevronDown
                  class="h-4 w-4 transition-transform duration-200 {isExpanded ? 'rotate-180' : ''}"
                />
              </div>
            </div>
          </div>
        </div>

        <!-- Expanded details -->
        {#if isExpanded}
          <div
            id={"admin-api-key-details-" + key.id}
            role="region"
            aria-label={"API key details for " + key.name}
            class="border-default bg-subtle/50 border-t px-5 py-4"
            transition:slide={{ duration: 200 }}
          >
            <div class="mb-4 flex items-center gap-2">
              <button
                type="button"
                onclick={() => setActiveTab(key.id, "overview")}
                class="rounded-md px-3 py-1.5 text-xs font-semibold transition-colors {activeTabByKey[
                  key.id
                ] !== 'usage'
                  ? 'bg-accent-default/10 text-accent-default'
                  : 'text-muted hover:text-default'}"
              >
                {m.api_keys_admin_tab_overview()}
              </button>
              <button
                type="button"
                onclick={() => setActiveTab(key.id, "usage")}
                class="rounded-md px-3 py-1.5 text-xs font-semibold transition-colors {activeTabByKey[
                  key.id
                ] === 'usage'
                  ? 'bg-accent-default/10 text-accent-default'
                  : 'text-muted hover:text-default'}"
              >
                {m.api_keys_admin_tab_usage()}
              </button>
            </div>

            {#if activeTabByKey[key.id] === "usage"}
              {@const usage = usageByKey[key.id]}
              <div class="space-y-4">
                {#if usageLoadingByKey[key.id]}
                  <div class="text-muted text-sm">{m.api_keys_admin_usage_loading()}</div>
                {:else if usageErrorByKey[key.id]}
                  <div class="text-sm text-red-600">{usageErrorByKey[key.id]}</div>
                {:else}
                  <div class="grid gap-3 md:grid-cols-4">
                    <div class="bg-primary border-default rounded-lg border p-3">
                      <p class="text-muted text-xs">{m.api_keys_admin_usage_total_events()}</p>
                      <p
                        class="text-default mt-1 text-lg font-semibold tabular-nums"
                        title={fullNumberFormatter.format(usage?.summary?.total_events ?? 0)}
                      >
                        {formatUsageMetric(usage?.summary?.total_events)}
                      </p>
                    </div>
                    <div class="bg-primary border-default rounded-lg border p-3">
                      <p class="text-muted text-xs">{m.api_keys_admin_usage_success_events()}</p>
                      <p
                        class="text-default mt-1 text-lg font-semibold tabular-nums"
                        title={fullNumberFormatter.format(usage?.summary?.used_events ?? 0)}
                      >
                        {formatUsageMetric(usage?.summary?.used_events)}
                      </p>
                    </div>
                    <div class="bg-primary border-default rounded-lg border p-3">
                      <p class="text-muted text-xs">{m.api_keys_admin_usage_failed_events()}</p>
                      <p
                        class="text-default mt-1 text-lg font-semibold tabular-nums"
                        title={fullNumberFormatter.format(usage?.summary?.auth_failed_events ?? 0)}
                      >
                        {formatUsageMetric(usage?.summary?.auth_failed_events)}
                      </p>
                    </div>
                    <div class="bg-primary border-default rounded-lg border p-3">
                      <p class="text-muted text-xs">{m.api_keys_last_used()}</p>
                      <p class="text-default mt-1 text-sm font-semibold">
                        {usage?.summary?.last_seen_at
                          ? formatter.format(new Date(usage.summary.last_seen_at))
                          : m.api_keys_never()}
                      </p>
                    </div>
                  </div>

                  {#if usage?.summary?.sampled_used_events}
                    <div
                      class="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-xs text-yellow-800 dark:border-yellow-900 dark:bg-yellow-900/20 dark:text-yellow-300"
                    >
                      <span class="inline-flex items-center gap-1.5">
                        <AlertTriangle class="h-3.5 w-3.5" />
                        {m.api_keys_admin_usage_sampled_notice()}
                      </span>
                    </div>
                  {/if}

                  {#if usage?.items?.length}
                    <div class="border-default overflow-hidden rounded-lg border">
                      <div class="max-h-[26rem] overflow-auto">
                        <table class="w-full min-w-[760px] text-sm">
                          <thead class="bg-subtle/80 text-muted sticky top-0 z-10">
                            <tr>
                              <th class="px-3 py-2 text-left font-medium">{m.audit_timestamp()}</th>
                              <th class="px-3 py-2 text-left font-medium">{m.audit_action()}</th>
                              <th class="px-3 py-2 text-left font-medium"
                                >{m.api_keys_admin_usage_request()}</th
                              >
                              <th class="px-3 py-2 text-left font-medium">IP / Origin</th>
                            </tr>
                          </thead>
                          <tbody>
                            {#each usage.items as event}
                              <tr class="border-default/60 border-t">
                                <td
                                  class="text-muted px-3 py-2 text-xs whitespace-nowrap tabular-nums"
                                >
                                  {formatter.format(new Date(event.timestamp))}
                                </td>
                                <td class="px-3 py-2">
                                  <span
                                    class="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium {event.action ===
                                    'api_key_auth_failed'
                                      ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
                                      : 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300'}"
                                  >
                                    {event.action}
                                  </span>
                                </td>
                                <td class="text-muted px-3 py-2 text-xs">
                                  <div class="flex items-center gap-1.5">
                                    <span class="shrink-0 font-medium">{event.method ?? "—"}</span>
                                    {#if event.request_path}
                                      <span class="text-muted/60">·</span>
                                      <span
                                        class="max-w-[24rem] truncate font-mono"
                                        title={event.request_path}>{event.request_path}</span
                                      >
                                    {/if}
                                  </div>
                                </td>
                                <td class="text-muted px-3 py-2 text-xs">
                                  <div class="flex items-center gap-1.5">
                                    <span class="shrink-0 font-mono">{event.ip_address ?? "—"}</span
                                    >
                                    {#if event.origin}
                                      <span class="text-muted/60">·</span>
                                      <span class="max-w-[18rem] truncate" title={event.origin}
                                        >{event.origin}</span
                                      >
                                    {/if}
                                  </div>
                                </td>
                              </tr>
                            {/each}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  {:else}
                    <div class="text-muted text-sm">{m.api_keys_admin_usage_empty()}</div>
                  {/if}

                  {#if usageCursorByKey[key.id]}
                    <button
                      type="button"
                      onclick={() => loadMoreUsage(key.id)}
                      class="border-default hover:bg-hover text-default rounded-md border px-3 py-1.5 text-xs font-medium transition-colors"
                    >
                      {m.api_keys_admin_usage_load_more()}
                    </button>
                  {/if}

                  <a
                    href={openAuditLogsForKey(key)}
                    class="text-accent-default hover:text-accent-default/80 inline-flex items-center gap-1.5 text-xs font-medium"
                  >
                    <Link class="h-3.5 w-3.5" />
                    {m.api_keys_admin_usage_open_audit_logs()}
                  </a>
                {/if}
              </div>
            {:else}
              <div class="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
                {#if key.description}
                  <div class="sm:col-span-2 lg:col-span-4">
                    <p class="text-muted text-sm">{key.description}</p>
                  </div>
                {/if}

                <div class="flex items-start gap-3">
                  <div class="bg-primary flex h-9 w-9 items-center justify-center rounded-lg">
                    <User class="text-muted h-4 w-4" />
                  </div>
                  <div>
                    <p class="text-muted text-xs">{m.api_keys_admin_owner_label()}</p>
                    <p class="text-default text-sm font-medium">
                      {getIdentityLabel(key.owner_user, key.owner_user_id)}
                    </p>
                    <p class="text-muted font-mono text-xs">{key.owner_user_id}</p>
                    {#if key.owner_user?.email}
                      <a
                        href={`/admin/users?tab=active&search=${encodeURIComponent(key.owner_user.email)}`}
                        class="text-accent-default hover:text-accent-default/80 mt-1 inline-flex items-center gap-1 text-xs font-medium"
                      >
                        <Link class="h-3 w-3" />
                        {m.api_keys_admin_view_user()}
                      </a>
                    {/if}
                  </div>
                </div>

                {#if key.created_by_user_id && key.created_by_user_id !== key.owner_user_id}
                  <div class="flex items-start gap-3">
                    <div class="bg-primary flex h-9 w-9 items-center justify-center rounded-lg">
                      <User class="text-muted h-4 w-4" />
                    </div>
                    <div>
                      <p class="text-muted text-xs">{m.api_keys_admin_created_by_label()}</p>
                      <p class="text-default text-sm font-medium">
                        {getIdentityLabel(key.created_by_user, key.created_by_user_id)}
                      </p>
                      <p class="text-muted font-mono text-xs">{key.created_by_user_id}</p>
                    </div>
                  </div>
                {/if}

                <div class="flex items-start gap-3">
                  <div class="bg-primary flex h-9 w-9 items-center justify-center rounded-lg">
                    <Calendar class="text-muted h-4 w-4" />
                  </div>
                  <div>
                    <p class="text-muted text-xs">{m.api_keys_created()}</p>
                    <p class="text-default text-sm font-medium">
                      {key.created_at ? formatter.format(new Date(key.created_at)) : "—"}
                    </p>
                  </div>
                </div>

                <div class="flex items-start gap-3">
                  <div class="bg-primary flex h-9 w-9 items-center justify-center rounded-lg">
                    <Activity class="text-muted h-4 w-4" />
                  </div>
                  <div>
                    <p class="text-muted text-xs">{m.api_keys_last_used()}</p>
                    <p class="text-default text-sm font-medium">
                      {key.last_used_at
                        ? formatter.format(new Date(key.last_used_at))
                        : m.api_keys_never()}
                    </p>
                  </div>
                </div>

                <div class="flex items-start gap-3">
                  <div class="bg-primary flex h-9 w-9 items-center justify-center rounded-lg">
                    <Clock class="text-muted h-4 w-4" />
                  </div>
                  <div>
                    <p class="text-muted text-xs">{m.api_keys_expires()}</p>
                    <p class="text-default text-sm font-medium">
                      {key.expires_at
                        ? formatter.format(new Date(key.expires_at))
                        : m.api_keys_never()}
                    </p>
                  </div>
                </div>

                <div class="flex items-start gap-3">
                  <div class="bg-primary flex h-9 w-9 items-center justify-center rounded-lg">
                    <Shield class="text-muted h-4 w-4" />
                  </div>
                  <div>
                    <p class="text-muted text-xs">{m.api_keys_rate_limit_label()}</p>
                    <p class="text-default text-sm font-medium">
                      {key.rate_limit ? `${key.rate_limit}/hr` : m.api_keys_default()}
                    </p>
                  </div>
                </div>

                {#if key.scope_id}
                  <div class="sm:col-span-2">
                    <p class="text-muted mb-2 text-xs">{m.api_keys_admin_scope_id_label()}</p>
                    {#if scopeNames[key.scope_id]}
                      <p class="text-default mb-2 text-sm font-medium">
                        {scopeNames[key.scope_id]}
                      </p>
                    {/if}
                    <code
                      class="bg-primary border-default text-default inline-block rounded-md border px-3 py-1.5 font-mono text-xs"
                    >
                      {key.scope_id}
                    </code>
                  </div>
                {/if}

                {#if key.key_type === "pk_" && key.allowed_origins?.length}
                  <div class="sm:col-span-2">
                    <p class="text-muted mb-2 text-xs">
                      {m.api_keys_admin_allowed_origins_label()}
                    </p>
                    <div class="flex flex-wrap gap-1.5">
                      {#each key.allowed_origins as origin}
                        <span
                          class="bg-primary border-default text-default inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-xs"
                        >
                          <Globe class="text-muted h-3 w-3" />
                          {origin}
                        </span>
                      {/each}
                    </div>
                  </div>
                {/if}

                {#if key.key_type === "sk_" && key.allowed_ips?.length}
                  <div class="sm:col-span-2">
                    <p class="text-muted mb-2 text-xs">{m.api_keys_admin_allowed_ips_label()}</p>
                    <div class="flex flex-wrap gap-1.5">
                      {#each key.allowed_ips as ip}
                        <span
                          class="bg-primary border-default text-default inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-xs"
                        >
                          <Server class="text-muted h-3 w-3" />
                          {ip}
                        </span>
                      {/each}
                    </div>
                  </div>
                {/if}
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}
