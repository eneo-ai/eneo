<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import { SvelteSet } from "svelte/reactivity";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { getReasonCodeLabel } from "$lib/features/api-keys/reasonCodeLabel";
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
    Bell,
    AlertTriangle
  } from "lucide-svelte";
  import { slide, fade } from "svelte/transition";
  import ApiKeyActions from "./ApiKeyActions.svelte";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import {
    getDaysUntilExpiration,
    getExpiryLevel,
    getEffectiveState
  } from "$lib/features/api-keys/expirationUtils";

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

  const intric = getIntric();

  let {
    keys = [],
    loading = false,
    onChanged,
    onSecret,
    followedKeyIds = new Set<string>(),
    scopeFollowed = false,
    onFollowChanged
  } = $props<{
    keys: ApiKeyV2[];
    loading: boolean;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
    followedKeyIds?: Set<string>;
    scopeFollowed?: boolean;
    onFollowChanged?: () => void | Promise<void>;
  }>();

  // Track expanded rows (SvelteSet is already reactive — no $state wrapper needed)
  let expandedIds = new SvelteSet<string>();
  let activeTabByKey = $state<Record<string, "overview" | "usage">>({});
  let usageByKey = $state<Record<string, ApiKeyUsageResponse>>({});
  let usageErrorByKey = $state<Record<string, string | null>>({});
  let usageLoadingByKey = $state<Record<string, boolean>>({});
  let usageCursorByKey = $state<Record<string, string | null>>({});

  // Track recently expanded rows for pulse animation
  let recentlyExpandedId = $state<string | null>(null);

  function toggleExpanded(id: string) {
    if (expandedIds.has(id)) {
      expandedIds.delete(id);
      recentlyExpandedId = null;
    } else {
      expandedIds.add(id);
      // Trigger pulse animation for newly expanded row
      recentlyExpandedId = id;
      setTimeout(() => {
        if (recentlyExpandedId === id) {
          recentlyExpandedId = null;
        }
      }, 600);
    }
    if (expandedIds.has(id) && !activeTabByKey[id]) {
      activeTabByKey = { ...activeTabByKey, [id]: "overview" };
    }
  }

  function setActiveTab(id: string, tab: "overview" | "usage") {
    activeTabByKey = { ...activeTabByKey, [id]: tab };
    if (tab === "usage") {
      void loadUsage(id, { reset: false });
    }
  }

  async function loadUsage(id: string, { reset }: { reset: boolean }) {
    if (usageLoadingByKey[id]) return;
    if (!reset && usageByKey[id]) return;

    usageLoadingByKey = { ...usageLoadingByKey, [id]: true };
    usageErrorByKey = { ...usageErrorByKey, [id]: null };
    try {
      const response = (await intric.apiKeys.getUsage({
        id,
        limit: 25
      })) as ApiKeyUsageResponse;
      usageByKey = { ...usageByKey, [id]: response };
      usageCursorByKey = { ...usageCursorByKey, [id]: response?.next_cursor ?? null };
    } catch (error) {
      console.error(error);
      usageErrorByKey = {
        ...usageErrorByKey,
        [id]: getErrorMessage(error)
      };
    } finally {
      usageLoadingByKey = { ...usageLoadingByKey, [id]: false };
    }
  }

  async function loadMoreUsage(id: string) {
    const cursor = usageCursorByKey[id];
    if (!cursor || usageLoadingByKey[id]) return;
    usageLoadingByKey = { ...usageLoadingByKey, [id]: true };
    usageErrorByKey = { ...usageErrorByKey, [id]: null };
    try {
      const response = (await intric.apiKeys.getUsage({
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
        [id]: getErrorMessage(error)
      };
    } finally {
      usageLoadingByKey = { ...usageLoadingByKey, [id]: false };
    }
  }

  // Status tooltip descriptions
  function getStatusTooltip(state: string): string {
    switch (state) {
      case "active":
        return m.api_keys_status_active_tooltip();
      case "suspended":
        return m.api_keys_status_suspended_tooltip();
      case "revoked":
        return m.api_keys_status_revoked_tooltip();
      case "expired":
        return m.api_keys_status_expired_tooltip();
      default:
        return m.api_keys_unknown_status();
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

  // Scope display helpers with theme-aware Tailwind classes
  function getScopeStyle(scopeType: string) {
    switch (scopeType) {
      case "tenant":
        return {
          label: m.api_keys_scope_tenant(),
          classes: "bg-gray-700 dark:bg-gray-600 text-white"
        };
      case "space":
        return {
          label: m.api_keys_scope_space(),
          classes: "bg-emerald-600 dark:bg-emerald-500 text-white"
        };
      case "assistant":
        return {
          label: m.api_keys_scope_assistant(),
          classes: "bg-violet-600 dark:bg-violet-500 text-white"
        };
      case "app":
        return {
          label: m.api_keys_scope_app(),
          classes: "bg-orange-600 dark:bg-orange-500 text-white"
        };
      default:
        return { label: m.api_keys_unknown(), classes: "bg-gray-500 dark:bg-gray-400 text-white" };
    }
  }

  function getScopeIcon(scopeType: string) {
    switch (scopeType) {
      case "tenant":
        return Building2;
      case "space":
        return Building2;
      case "assistant":
        return MessageSquare;
      case "app":
        return AppWindow;
      default:
        return Building2;
    }
  }

  function getStateStyle(state: string) {
    switch (state) {
      case "active":
        return {
          label: m.api_keys_status_active(),
          dotClasses: "bg-emerald-500 dark:bg-emerald-400"
        };
      case "suspended":
        return {
          label: m.api_keys_status_suspended(),
          dotClasses: "bg-amber-500 dark:bg-amber-400"
        };
      case "revoked":
        return { label: m.api_keys_status_revoked(), dotClasses: "bg-red-500 dark:bg-red-400" };
      case "expired":
        return { label: m.api_keys_status_expired(), dotClasses: "bg-gray-400 dark:bg-gray-500" };
      default:
        return { label: m.api_keys_unknown(), dotClasses: "bg-gray-400 dark:bg-gray-500" };
    }
  }

  function getPermissionStyle(permission: string) {
    switch (permission) {
      case "read":
        return {
          label: m.api_keys_permission_read(),
          classes: "bg-sky-600 dark:bg-sky-500 text-white"
        };
      case "write":
        return {
          label: m.api_keys_permission_write(),
          classes: "bg-purple-500 dark:bg-purple-400 text-white"
        };
      case "admin":
        return {
          label: m.api_keys_permission_admin(),
          classes: "bg-rose-600 dark:bg-rose-500 text-white"
        };
      default:
        return { label: permission, classes: "bg-gray-500 dark:bg-gray-400 text-white" };
    }
  }

  function getKeyTypeStyle(keyType: string) {
    // Using theme-aware classes that work in both light and dark mode
    return keyType === "pk_"
      ? {
          label: m.api_keys_public_key(),
          iconClass: "text-amber-600 dark:text-amber-400",
          bgClass: "bg-amber-50 dark:bg-amber-900/30"
        }
      : {
          label: m.api_keys_secret_key(),
          iconClass: "text-indigo-600 dark:text-indigo-400",
          bgClass: "bg-indigo-50 dark:bg-indigo-900/30"
        };
  }
</script>

{#if loading}
  <!-- Skeleton loader with theme-aware colors -->
  <div class="space-y-3">
    {#each Array(3) as _, i (i)}
      <div
        class="border-default bg-primary rounded-xl border p-4"
        style="animation: skeleton-pulse 1.5s ease-in-out infinite; animation-delay: {i * 100}ms;"
      >
        <div class="flex items-center gap-4">
          <div class="bg-secondary h-11 w-11 rounded-xl"></div>
          <div class="flex-1 space-y-2.5">
            <div class="bg-secondary h-4 w-36 rounded-md"></div>
            <div class="flex gap-2">
              <div class="bg-secondary h-3 w-24 rounded-md"></div>
              <div class="bg-secondary h-3 w-16 rounded-md"></div>
            </div>
          </div>
          <div class="hidden items-center gap-4 sm:flex">
            <div class="bg-secondary h-8 w-20 rounded-md"></div>
            <div class="bg-secondary h-8 w-20 rounded-md"></div>
          </div>
          <div class="bg-secondary h-8 w-8 rounded-lg"></div>
        </div>
      </div>
    {/each}
  </div>
{:else if keys.length === 0}
  <!-- Empty state with smooth hover -->
  <div
    class="border-default bg-subtle/30 hover:border-dimmer hover:bg-subtle/50 rounded-xl border-2 border-dashed
           p-12 text-center transition-all duration-200"
  >
    <div
      class="bg-accent-default/10 mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl
             transition-transform duration-200 hover:scale-105"
    >
      <Key class="text-accent-default h-8 w-8" />
    </div>
    <h3 class="text-default text-lg font-semibold">{m.api_keys_no_keys()}</h3>
    <p class="text-muted mx-auto mt-2 max-w-md text-sm">
      {m.api_keys_no_keys_desc()}
    </p>
  </div>
{:else}
  <!-- Key list -->
  <div class="space-y-3">
    {#each keys as key (key.id)}
      {@const isExpanded = expandedIds.has(key.id)}
      {@const scope = getScopeStyle(key.scope_type)}
      {@const ScopeIcon = getScopeIcon(key.scope_type)}
      {@const effectiveState = getEffectiveState(key)}
      {@const state = getStateStyle(effectiveState)}
      {@const permission = getPermissionStyle(key.permission)}
      {@const keyTypeStyle = getKeyTypeStyle(key.key_type)}
      {@const KeyIcon = key.key_type === "pk_" ? Globe : Lock}
      {@const daysUntil = getDaysUntilExpiration(key.expires_at)}

      <div
        class="group border-default bg-primary hover:border-dimmer overflow-hidden rounded-xl border transition-all
               duration-200 hover:-translate-y-px hover:shadow-md
               {isExpanded
          ? 'ring-accent-default/20 border-accent-default/30 shadow-sm ring-2'
          : ''}
               {recentlyExpandedId === key.id ? 'animate-expand-pulse' : ''}"
      >
        <!-- Main row -->
        <button
          type="button"
          onclick={() => toggleExpanded(key.id)}
          aria-expanded={isExpanded}
          aria-controls="details-{key.id}"
          class="focus-visible:ring-accent-default/50 w-full rounded-t-xl px-5 py-4 text-left focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none
                 {effectiveState === 'revoked' || effectiveState === 'expired' ? 'opacity-60' : ''}"
        >
          <div class="flex items-center gap-4">
            <!-- Key type icon -->
            <div
              class="flex h-11 w-11 items-center justify-center rounded-xl {keyTypeStyle.bgClass}"
            >
              <KeyIcon class="h-5 w-5 {keyTypeStyle.iconClass}" />
            </div>

            <!-- Key info -->
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-3">
                <span class="flex items-center gap-1.5">
                  <h4 class="text-default truncate font-semibold">{key.name}</h4>
                  {#if followedKeyIds.has(key.id)}
                    <Bell class="text-accent-default h-3.5 w-3.5 shrink-0" />
                  {/if}
                </span>

                <!-- Status dot and badge with tooltip -->
                <div class="group/status relative flex items-center gap-1.5">
                  <span
                    class="h-2.5 w-2.5 rounded-full {state.dotClasses}"
                    title={getStatusTooltip(effectiveState)}
                  ></span>
                  <span class="text-muted text-xs">{state.label}</span>
                  <!-- Tooltip on hover -->
                  <div class="absolute top-full left-0 z-10 mt-1 hidden group-hover/status:block">
                    <div
                      class="bg-primary border-default text-muted rounded-lg border px-3 py-2 text-xs whitespace-nowrap shadow-lg"
                    >
                      {getStatusTooltip(effectiveState)}
                    </div>
                  </div>
                </div>
              </div>

              <!-- Key preview with copy hint -->
              <div class="mt-1.5 flex flex-wrap items-center gap-2.5 text-sm">
                <code
                  class="text-muted bg-subtle inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-xs"
                >
                  {key.key_type}<span class="opacity-30">····</span>{key.key_suffix}
                </code>

                <!-- Scope badge - theme-aware with Tailwind classes -->
                <span
                  class="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold ring-1 ring-white/20 ring-inset {scope.classes}"
                >
                  <ScopeIcon class="h-3 w-3" />
                  {scope.label}
                  {#if key.scope_id}
                    <span class="opacity-80">· {key.scope_id.slice(0, 8)}</span>
                  {/if}
                </span>

                <!-- Permission badge - theme-aware with shadow for depth -->
                <span
                  class="rounded-md px-2.5 py-1 text-xs font-bold tracking-wide uppercase {permission.classes}"
                >
                  {permission.label}
                </span>

                <!-- Service key badge -->
                {#if key.ownership === "service"}
                  <span
                    class="inline-flex items-center gap-1 rounded-md bg-cyan-600 px-2.5 py-1 text-xs font-semibold text-white ring-1 ring-white/20 ring-inset dark:bg-cyan-500"
                  >
                    <Server class="h-3 w-3" />
                    {m.api_keys_ownership_service_badge()}
                  </span>
                {/if}
              </div>
            </div>

            <!-- Right side info -->
            <div
              class="hidden items-center gap-6 text-sm sm:flex"
              style="font-variant-numeric: tabular-nums"
            >
              <!-- Expiration -->
              {#if daysUntil !== null}
                {@const expiryLevel = getExpiryLevel(daysUntil)}
                <div class="flex items-center gap-1.5 text-right">
                  {#if expiryLevel === "urgent" || expiryLevel === "expired"}
                    <span class="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-red-500"></span>
                  {:else if expiryLevel === "warning"}
                    <span class="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-yellow-500"></span>
                  {/if}
                  <div>
                    <p class="text-muted text-xs">{m.api_keys_expires()}</p>
                    <p
                      class="font-medium {expiryLevel === 'expired' || expiryLevel === 'urgent'
                        ? 'text-red-600 dark:text-red-400'
                        : expiryLevel === 'warning' || expiryLevel === 'notice'
                          ? 'text-yellow-600 dark:text-yellow-400'
                          : 'text-default'}"
                    >
                      {daysUntil < 0
                        ? m.api_keys_status_expired()
                        : daysUntil === 0
                          ? m.api_keys_today()
                          : daysUntil === 1
                            ? m.api_keys_tomorrow()
                            : m.api_keys_days({ count: daysUntil })}
                    </p>
                  </div>
                </div>
              {/if}

              <!-- Last used -->
              <div class="text-right">
                <p class="text-muted text-xs">{m.api_keys_last_used()}</p>
                <p class="text-default font-medium">{formatRelativeDate(key.last_used_at)}</p>
              </div>
            </div>

            <!-- Actions and expand -->
            <div class="flex items-center gap-2">
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div onclick={(e) => e.stopPropagation()}>
                <ApiKeyActions
                  apiKey={key}
                  {onChanged}
                  {onSecret}
                  isFollowed={followedKeyIds?.has(key.id) ?? false}
                  isFollowedViaScope={scopeFollowed && !(followedKeyIds?.has(key.id) ?? false)}
                  {onFollowChanged}
                />
              </div>

              <div
                class="text-muted bg-subtle/40 group-hover:bg-subtle flex h-8 w-8 items-center
                       justify-center rounded-lg transition-colors"
              >
                <ChevronDown
                  class="h-4 w-4 transition-transform duration-200 {isExpanded ? 'rotate-180' : ''}"
                />
              </div>
            </div>
          </div>
        </button>

        <!-- Expanded details -->
        {#if isExpanded}
          <div
            id="details-{key.id}"
            class="border-default from-secondary/40 to-secondary/20 border-t bg-gradient-to-b px-5 py-5"
            transition:slide={{ duration: 200 }}
          >
            <!-- Tab switcher -->
            <div class="bg-subtle/80 mb-4 inline-flex items-center gap-1 rounded-lg p-1">
              <button
                type="button"
                onclick={() => setActiveTab(key.id, "overview")}
                class="rounded-md px-3.5 py-1.5 text-sm font-semibold transition-all duration-150 {activeTabByKey[
                  key.id
                ] !== 'usage'
                  ? 'bg-primary text-default shadow-sm'
                  : 'text-dimmer hover:text-default'}"
              >
                {m.api_keys_admin_tab_overview()}
              </button>
              <button
                type="button"
                onclick={() => setActiveTab(key.id, "usage")}
                class="rounded-md px-3.5 py-1.5 text-sm font-semibold transition-all duration-150 {activeTabByKey[
                  key.id
                ] === 'usage'
                  ? 'bg-primary text-default shadow-sm'
                  : 'text-dimmer hover:text-default'}"
              >
                {m.api_keys_admin_tab_usage()}
              </button>
            </div>

            {#key activeTabByKey[key.id]}
              <div in:fade={{ duration: 150, delay: 50 }}>
                {#if activeTabByKey[key.id] === "usage"}
                  {@const usage = usageByKey[key.id]}
                  <div class="space-y-4">
                    {#if usageLoadingByKey[key.id]}
                      <div class="text-muted text-sm">{m.api_keys_admin_usage_loading()}</div>
                    {:else if usageErrorByKey[key.id]}
                      <div class="text-negative text-sm">{usageErrorByKey[key.id]}</div>
                    {:else}
                      <div class="grid gap-3 md:grid-cols-4">
                        <div class="bg-primary/50 border-default rounded-lg border p-3">
                          <p class="text-muted text-xs">{m.api_keys_admin_usage_total_events()}</p>
                          <p
                            class="text-default mt-1 text-lg font-semibold tabular-nums"
                            title={fullNumberFormatter.format(usage?.summary?.total_events ?? 0)}
                          >
                            {formatUsageMetric(usage?.summary?.total_events)}
                          </p>
                        </div>
                        <div class="bg-primary/50 border-default rounded-lg border p-3">
                          <p class="text-muted text-xs">
                            {m.api_keys_admin_usage_success_events()}
                          </p>
                          <p
                            class="{(usage?.summary?.used_events ?? 0) > 0
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : 'text-default'} mt-1 text-lg font-semibold tabular-nums"
                            title={fullNumberFormatter.format(usage?.summary?.used_events ?? 0)}
                          >
                            {formatUsageMetric(usage?.summary?.used_events)}
                          </p>
                        </div>
                        <div class="bg-primary/50 border-default rounded-lg border p-3">
                          <p class="text-muted text-xs">{m.api_keys_admin_usage_failed_events()}</p>
                          <p
                            class="{(usage?.summary?.auth_failed_events ?? 0) > 0
                              ? 'text-red-600 dark:text-red-400'
                              : 'text-default'} mt-1 text-lg font-semibold tabular-nums"
                            title={fullNumberFormatter.format(
                              usage?.summary?.auth_failed_events ?? 0
                            )}
                          >
                            {formatUsageMetric(usage?.summary?.auth_failed_events)}
                          </p>
                        </div>
                        <div class="bg-primary/50 border-default rounded-lg border p-3">
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
                                  <th class="px-3 py-2 text-left font-medium"
                                    >{m.audit_timestamp()}</th
                                  >
                                  <th class="px-3 py-2 text-left font-medium">{m.audit_action()}</th
                                  >
                                  <th class="px-3 py-2 text-left font-medium"
                                    >{m.api_keys_admin_usage_request()}</th
                                  >
                                  <th class="px-3 py-2 text-left font-medium"
                                    >{m.api_keys_admin_usage_ip_origin()}</th
                                  >
                                </tr>
                              </thead>
                              <tbody>
                                {#each usage.items as event (event.id)}
                                  <tr
                                    class="border-default/60 hover:bg-subtle/40 even:bg-subtle/20 border-t transition-colors"
                                  >
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
                                        <span class="shrink-0 font-medium"
                                          >{event.method ?? "—"}</span
                                        >
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
                                        <span class="shrink-0 font-mono"
                                          >{event.ip_address ?? "—"}</span
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
                    {/if}
                  </div>
                {:else}
                  <!-- Overview tab (original details) -->
                  <!-- Description section -->
                  {#if key.description}
                    <div class="border-dimmer mb-5 border-b pb-4">
                      <p class="text-default text-sm leading-relaxed">{key.description}</p>
                    </div>
                  {/if}

                  <!-- Details grid with visual separation -->
                  <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                    <!-- Created -->
                    <div
                      class="bg-primary/50 border-default flex items-start gap-3 rounded-lg border p-3
                         transition-colors duration-200"
                    >
                      <div class="bg-subtle flex h-8 w-8 items-center justify-center rounded-lg">
                        <Calendar class="text-muted h-4 w-4" />
                      </div>
                      <div class="min-w-0 flex-1">
                        <p class="text-muted text-[11px] font-medium tracking-wider uppercase">
                          {m.api_keys_created()}
                        </p>
                        <p class="text-default mt-0.5 truncate text-sm font-medium">
                          {key.created_at ? formatter.format(new Date(key.created_at)) : "—"}
                        </p>
                      </div>
                    </div>

                    <!-- Last used -->
                    <div
                      class="bg-primary/50 border-default flex items-start gap-3 rounded-lg border p-3
                         transition-colors duration-200"
                    >
                      <div class="bg-subtle flex h-8 w-8 items-center justify-center rounded-lg">
                        <Activity class="text-muted h-4 w-4" />
                      </div>
                      <div class="min-w-0 flex-1">
                        <p class="text-muted text-[11px] font-medium tracking-wider uppercase">
                          {m.api_keys_last_used()}
                        </p>
                        <p class="text-default mt-0.5 truncate text-sm font-medium">
                          {key.last_used_at
                            ? formatter.format(new Date(key.last_used_at))
                            : m.api_keys_never()}
                        </p>
                      </div>
                    </div>

                    <!-- Expires -->
                    <div
                      class="bg-primary/50 border-default flex items-start gap-3 rounded-lg border p-3
                         transition-colors duration-200"
                    >
                      <div class="bg-subtle flex h-8 w-8 items-center justify-center rounded-lg">
                        <Clock class="text-muted h-4 w-4" />
                      </div>
                      <div class="min-w-0 flex-1">
                        <p class="text-muted text-[11px] font-medium tracking-wider uppercase">
                          {m.api_keys_expires()}
                        </p>
                        <p class="text-default mt-0.5 truncate text-sm font-medium">
                          {key.expires_at
                            ? formatter.format(new Date(key.expires_at))
                            : m.api_keys_never()}
                        </p>
                      </div>
                    </div>

                    <!-- Rate limit -->
                    <div
                      class="bg-primary/50 border-default flex items-start gap-3 rounded-lg border p-3
                         transition-colors duration-200"
                    >
                      <div class="bg-subtle flex h-8 w-8 items-center justify-center rounded-lg">
                        <Shield class="text-muted h-4 w-4" />
                      </div>
                      <div class="min-w-0 flex-1">
                        <p class="text-muted text-[11px] font-medium tracking-wider uppercase">
                          {m.api_keys_rate_limit_label()}
                        </p>
                        <p class="text-default mt-0.5 truncate text-sm font-medium">
                          {key.rate_limit
                            ? m.api_keys_rate_limit_value({ count: key.rate_limit })
                            : m.api_keys_default()}
                        </p>
                      </div>
                    </div>
                  </div>

                  <!-- Allowed Origins (for pk_ keys) -->
                  {#if key.key_type === "pk_" && key.allowed_origins?.length}
                    <div class="border-dimmer mt-5 border-t pt-4">
                      <p class="text-muted mb-2.5 text-[11px] font-medium tracking-wider uppercase">
                        {m.api_keys_allowed_origins()}
                      </p>
                      <div class="flex flex-wrap gap-2">
                        {#each key.allowed_origins as origin (origin)}
                          <span
                            class="bg-primary border-default text-default hover:border-dimmer hover:bg-subtle inline-flex items-center
                               gap-1.5 rounded-lg border px-3 py-1.5
                               font-mono text-xs transition-all duration-200"
                          >
                            <Globe class="text-muted h-3.5 w-3.5" />
                            {origin}
                          </span>
                        {/each}
                      </div>
                    </div>
                  {/if}

                  <!-- Allowed IPs (for sk_ keys) -->
                  {#if key.key_type === "sk_" && key.allowed_ips?.length}
                    <div class="border-dimmer mt-5 border-t pt-4">
                      <p class="text-muted mb-2.5 text-[11px] font-medium tracking-wider uppercase">
                        {m.api_keys_allowed_ips()}
                      </p>
                      <div class="flex flex-wrap gap-2">
                        {#each key.allowed_ips as ip (ip)}
                          <span
                            class="bg-primary border-default text-default hover:border-dimmer hover:bg-subtle inline-flex items-center
                               gap-1.5 rounded-lg border px-3 py-1.5
                               font-mono text-xs transition-all duration-200"
                          >
                            <Server class="text-muted h-3.5 w-3.5" />
                            {ip}
                          </span>
                        {/each}
                      </div>
                    </div>
                  {/if}

                  <!-- Suspension info -->
                  {#if key.state === "suspended" && key.suspended_at}
                    {@const suspendedReasonLabel = getReasonCodeLabel(key.suspended_reason_code)}
                    <div class="border-dimmer mt-5 border-t pt-4">
                      <div
                        class="border-caution/40 bg-caution/10 dark:border-caution/30 dark:bg-caution/5 rounded-lg
                           border p-4"
                      >
                        <div class="flex items-start gap-3">
                          <div
                            class="bg-caution/20 flex h-8 w-8 items-center justify-center rounded-lg"
                          >
                            <Shield class="text-caution h-4 w-4" />
                          </div>
                          <div class="min-w-0 flex-1">
                            <p class="text-caution text-sm font-semibold">
                              {m.api_keys_key_suspended()}
                            </p>
                            <p class="text-caution/80 mt-1 text-sm">
                              {formatter.format(new Date(key.suspended_at))}
                            </p>
                            {#if suspendedReasonLabel}
                              <p class="text-caution/70 mt-2 text-sm">{suspendedReasonLabel}</p>
                            {/if}
                            {#if key.suspended_reason_text}
                              <p class="text-caution/60 mt-1 text-xs">
                                {key.suspended_reason_text}
                              </p>
                            {/if}
                          </div>
                        </div>
                      </div>
                    </div>
                  {/if}

                  <!-- Revocation info -->
                  {#if key.state === "revoked" && key.revoked_at}
                    {@const revokedReasonLabel = getReasonCodeLabel(key.revoked_reason_code)}
                    <div class="border-dimmer mt-5 border-t pt-4">
                      <div
                        class="border-negative/40 bg-negative/10 dark:border-negative/30 dark:bg-negative/5 rounded-lg
                           border p-4"
                      >
                        <div class="flex items-start gap-3">
                          <div
                            class="bg-negative/20 flex h-8 w-8 items-center justify-center rounded-lg"
                          >
                            <Lock class="text-negative h-4 w-4" />
                          </div>
                          <div class="min-w-0 flex-1">
                            <p class="text-negative text-sm font-semibold">
                              {m.api_keys_key_revoked()}
                            </p>
                            <p class="text-negative/80 mt-1 text-sm">
                              {formatter.format(new Date(key.revoked_at))}
                            </p>
                            {#if revokedReasonLabel}
                              <p class="text-negative/70 mt-2 text-sm">{revokedReasonLabel}</p>
                            {/if}
                            {#if key.revoked_reason_text}
                              <p class="text-negative/60 mt-1 text-xs">{key.revoked_reason_text}</p>
                            {/if}
                          </div>
                        </div>
                      </div>
                    </div>
                  {/if}
                {/if}
              </div>
            {/key}
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  /* Theme-aware skeleton pulse animation */
  @keyframes skeleton-pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.4;
    }
  }

  /* Subtle pulse animation for newly expanded rows */
  @keyframes expand-pulse {
    0% {
      box-shadow: 0 0 0 0 rgba(var(--color-accent-default-rgb, 99, 102, 241), 0.4);
    }
    70% {
      box-shadow: 0 0 0 8px rgba(var(--color-accent-default-rgb, 99, 102, 241), 0);
    }
    100% {
      box-shadow: 0 0 0 0 rgba(var(--color-accent-default-rgb, 99, 102, 241), 0);
    }
  }

  :global(.animate-expand-pulse) {
    animation: expand-pulse 0.6s ease-out;
  }

  @media (prefers-reduced-motion: reduce) {
    @keyframes skeleton-pulse {
      0%,
      100% {
        opacity: 0.7;
      }
    }

    :global(.animate-expand-pulse) {
      animation: none;
    }
  }
</style>
