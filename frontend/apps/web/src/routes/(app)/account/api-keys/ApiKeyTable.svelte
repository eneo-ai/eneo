<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import { Button, Label } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
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
    Copy
  } from "lucide-svelte";
  import { slide, fly } from "svelte/transition";
  import ApiKeyActions from "./ApiKeyActions.svelte";

  let { keys = [], loading = false, onChanged, onSecret } = $props<{
    keys: ApiKeyV2[];
    loading: boolean;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
  }>();

  // Track expanded rows
  let expandedIds = $state<Set<string>>(new Set());

  // Track if user has ever expanded a row (for hint display)
  let hasExpandedAny = $state(false);

  // Track recently expanded rows for pulse animation
  let recentlyExpandedId = $state<string | null>(null);

  function toggleExpanded(id: string) {
    if (expandedIds.has(id)) {
      expandedIds.delete(id);
      recentlyExpandedId = null;
    } else {
      expandedIds.add(id);
      hasExpandedAny = true;
      // Trigger pulse animation for newly expanded row
      recentlyExpandedId = id;
      setTimeout(() => {
        if (recentlyExpandedId === id) {
          recentlyExpandedId = null;
        }
      }, 600);
    }
    expandedIds = new Set(expandedIds);
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
        return "Unknown status";
    }
  }

  const formatter = new Intl.DateTimeFormat("sv-SE", {
    dateStyle: "medium",
    timeStyle: "short"
  });

  const relativeFormatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

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

  // Scope display helpers with theme-aware Tailwind classes
  function getScopeStyle(scopeType: string) {
    switch (scopeType) {
      case "tenant":
        return { label: m.api_keys_scope_tenant(), classes: "bg-gray-700 dark:bg-gray-600 text-white" };
      case "space":
        return { label: m.api_keys_scope_space(), classes: "bg-emerald-600 dark:bg-emerald-500 text-white" };
      case "assistant":
        return { label: m.api_keys_scope_assistant(), classes: "bg-violet-600 dark:bg-violet-500 text-white" };
      case "app":
        return { label: m.api_keys_scope_app(), classes: "bg-orange-600 dark:bg-orange-500 text-white" };
      default:
        return { label: "Unknown", classes: "bg-gray-500 dark:bg-gray-400 text-white" };
    }
  }

  function getScopeIcon(scopeType: string) {
    switch (scopeType) {
      case "tenant": return Building2;
      case "space": return Building2;
      case "assistant": return MessageSquare;
      case "app": return AppWindow;
      default: return Building2;
    }
  }

  function getStateStyle(state: string) {
    switch (state) {
      case "active":
        return { label: m.api_keys_status_active(), dotClasses: "bg-emerald-500 dark:bg-emerald-400" };
      case "suspended":
        return { label: m.api_keys_status_suspended(), dotClasses: "bg-amber-500 dark:bg-amber-400" };
      case "revoked":
        return { label: m.api_keys_status_revoked(), dotClasses: "bg-red-500 dark:bg-red-400" };
      case "expired":
        return { label: m.api_keys_status_expired(), dotClasses: "bg-gray-400 dark:bg-gray-500" };
      default:
        return { label: "Unknown", dotClasses: "bg-gray-400 dark:bg-gray-500" };
    }
  }

  function getPermissionStyle(permission: string) {
    switch (permission) {
      case "read":
        return { classes: "bg-sky-600 dark:bg-sky-500 text-white" };
      case "write":
        return { classes: "bg-purple-500 dark:bg-purple-400 text-white" };
      case "admin":
        return { classes: "bg-red-600 dark:bg-red-500 text-white" };
      default:
        return { classes: "bg-gray-500 dark:bg-gray-400 text-white" };
    }
  }

  function getKeyTypeStyle(keyType: string) {
    // Using theme-aware classes that work in both light and dark mode
    return keyType === "pk_"
      ? { label: m.api_keys_public_key(), iconClass: "text-amber-600 dark:text-amber-400", bgClass: "bg-amber-50 dark:bg-amber-900/30" }
      : { label: m.api_keys_secret_key(), iconClass: "text-indigo-600 dark:text-indigo-400", bgClass: "bg-indigo-50 dark:bg-indigo-900/30" };
  }
</script>

{#if loading}
  <!-- Skeleton loader with theme-aware colors -->
  <div class="space-y-3">
    {#each Array(3) as _, i}
      <div
        class="rounded-xl border border-default bg-primary p-4"
        style="animation: skeleton-pulse 1.5s ease-in-out infinite; animation-delay: {i * 100}ms;"
      >
        <div class="flex items-center gap-4">
          <div class="h-11 w-11 rounded-xl bg-secondary"></div>
          <div class="flex-1 space-y-2.5">
            <div class="h-4 w-36 rounded-md bg-secondary"></div>
            <div class="flex gap-2">
              <div class="h-3 w-24 rounded-md bg-secondary"></div>
              <div class="h-3 w-16 rounded-md bg-secondary"></div>
            </div>
          </div>
          <div class="hidden sm:flex items-center gap-4">
            <div class="h-8 w-20 rounded-md bg-secondary"></div>
            <div class="h-8 w-20 rounded-md bg-secondary"></div>
          </div>
          <div class="h-8 w-8 rounded-lg bg-secondary"></div>
        </div>
      </div>
    {/each}
  </div>
{:else if keys.length === 0}
  <!-- Empty state with smooth hover -->
  <div
    class="rounded-xl border-2 border-dashed border-default bg-subtle/30 p-12 text-center
           transition-all duration-200 hover:border-dimmer hover:bg-subtle/50"
  >
    <div
      class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-default/10
             transition-transform duration-200 hover:scale-105"
    >
      <Key class="h-8 w-8 text-accent-default" />
    </div>
    <h3 class="text-lg font-semibold text-default">{m.api_keys_no_keys()}</h3>
    <p class="mt-2 text-sm text-muted max-w-md mx-auto">
      {m.api_keys_no_keys_desc()}
    </p>
  </div>
{:else}
  <!-- Key list -->
  <div class="space-y-3">
    {#if !hasExpandedAny && keys.length > 0}
      <p class="text-xs text-muted text-center mb-2 opacity-70">
        {m.api_keys_click_to_view()}
      </p>
    {/if}
    {#each keys as key (key.id)}
      {@const isExpanded = expandedIds.has(key.id)}
      {@const scope = getScopeStyle(key.scope_type)}
      {@const ScopeIcon = getScopeIcon(key.scope_type)}
      {@const state = getStateStyle(key.state)}
      {@const permission = getPermissionStyle(key.permission)}
      {@const keyTypeStyle = getKeyTypeStyle(key.key_type)}
      {@const KeyIcon = key.key_type === "pk_" ? Globe : Lock}
      {@const daysUntil = getDaysUntilExpiration(key.expires_at)}

      <div
        class="group rounded-xl border border-default bg-primary overflow-hidden transition-all duration-200
               hover:shadow-md hover:border-dimmer hover:scale-[1.005]
               {isExpanded ? 'ring-2 ring-accent-default/20 border-accent-default/30' : ''}
               {recentlyExpandedId === key.id ? 'animate-expand-pulse' : ''}"
      >
        <!-- Main row -->
        <button
          type="button"
          onclick={() => toggleExpanded(key.id)}
          aria-expanded={isExpanded}
          aria-controls="details-{key.id}"
          class="w-full px-5 py-4 text-left"
        >
          <div class="flex items-center gap-4">
            <!-- Key type icon -->
            <div class="flex h-11 w-11 items-center justify-center rounded-xl {keyTypeStyle.bgClass}">
              <KeyIcon class="h-5 w-5 {keyTypeStyle.iconClass}" />
            </div>

            <!-- Key info -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-3 flex-wrap">
                <h4 class="font-semibold text-default truncate">{key.name}</h4>

                <!-- Status dot and badge with tooltip -->
                <div class="flex items-center gap-1.5 group/status relative">
                  <span class="h-2 w-2 rounded-full {state.dotClasses}" title={getStatusTooltip(key.state)}></span>
                  <span class="text-xs text-muted">{state.label}</span>
                  <!-- Tooltip on hover -->
                  <div class="absolute left-0 top-full mt-1 z-10 hidden group-hover/status:block">
                    <div class="bg-primary border border-default rounded-lg shadow-lg px-3 py-2 text-xs text-muted whitespace-nowrap">
                      {getStatusTooltip(key.state)}
                    </div>
                  </div>
                </div>
              </div>

              <!-- Key preview with copy hint -->
              <div class="mt-1.5 flex items-center gap-2.5 flex-wrap text-sm">
                <code class="group/key font-mono text-muted inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-subtle/50 hover:bg-subtle transition-colors cursor-default">
                  {key.key_type}<span class="opacity-40">•••</span>{key.key_suffix}
                  <Copy class="h-3 w-3 opacity-0 group-hover/key:opacity-50 transition-opacity" />
                </code>

                <!-- Scope badge - theme-aware with Tailwind classes -->
                <span
                  class="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold {scope.classes}"
                >
                  <ScopeIcon class="h-3 w-3" />
                  {scope.label}
                  {#if key.scope_id}
                    <span class="opacity-80">· {key.scope_id.slice(0, 8)}</span>
                  {/if}
                </span>

                <!-- Permission badge - theme-aware with shadow for depth -->
                <span
                  class="rounded-md px-2.5 py-1 text-xs font-bold uppercase tracking-wide shadow-sm {permission.classes}"
                >
                  {key.permission}
                </span>
              </div>
            </div>

            <!-- Right side info -->
            <div class="hidden sm:flex items-center gap-6 text-sm">
              <!-- Expiration -->
              {#if daysUntil !== null}
                <div class="text-right">
                  <p class="text-xs text-muted">{m.api_keys_expires()}</p>
                  <p class="font-medium {daysUntil <= 7 ? 'text-caution' : daysUntil <= 0 ? 'text-negative' : 'text-default'}">
                    {daysUntil <= 0 ? m.api_keys_status_expired() : daysUntil === 1 ? m.api_keys_tomorrow() : m.api_keys_days({ count: daysUntil })}
                  </p>
                </div>
              {/if}

              <!-- Last used -->
              <div class="text-right">
                <p class="text-xs text-muted">{m.api_keys_last_used()}</p>
                <p class="font-medium text-default">{formatRelativeDate(key.last_used_at)}</p>
              </div>
            </div>

            <!-- Actions and expand -->
            <div class="flex items-center gap-2">
              <ApiKeyActions apiKey={key} {onChanged} {onSecret} />

              <div
                class="flex h-8 w-8 items-center justify-center rounded-lg text-muted
                       group-hover:bg-subtle transition-colors"
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
            class="border-t border-default bg-secondary/50 px-5 py-5"
            transition:slide={{ duration: 200 }}
          >
            <!-- Description section -->
            {#if key.description}
              <div class="mb-5 pb-4 border-b border-dimmer">
                <p class="text-sm text-muted leading-relaxed">{key.description}</p>
              </div>
            {/if}

            <!-- Details grid with visual separation -->
            <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <!-- Created -->
              <div
                class="flex items-start gap-3 p-3 rounded-lg bg-primary/50 border border-default
                       transition-all duration-200 hover:bg-primary hover:border-dimmer"
              >
                <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-subtle border border-dimmer">
                  <Calendar class="h-4 w-4 text-muted" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-xs font-medium text-muted uppercase tracking-wide">{m.api_keys_created()}</p>
                  <p class="text-sm font-medium text-default mt-0.5 truncate">
                    {key.created_at ? formatter.format(new Date(key.created_at)) : "—"}
                  </p>
                </div>
              </div>

              <!-- Last used -->
              <div
                class="flex items-start gap-3 p-3 rounded-lg bg-primary/50 border border-default
                       transition-all duration-200 hover:bg-primary hover:border-dimmer"
              >
                <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-subtle border border-dimmer">
                  <Activity class="h-4 w-4 text-muted" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-xs font-medium text-muted uppercase tracking-wide">{m.api_keys_last_used()}</p>
                  <p class="text-sm font-medium text-default mt-0.5 truncate">
                    {key.last_used_at ? formatter.format(new Date(key.last_used_at)) : m.api_keys_never()}
                  </p>
                </div>
              </div>

              <!-- Expires -->
              <div
                class="flex items-start gap-3 p-3 rounded-lg bg-primary/50 border border-default
                       transition-all duration-200 hover:bg-primary hover:border-dimmer"
              >
                <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-subtle border border-dimmer">
                  <Clock class="h-4 w-4 text-muted" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-xs font-medium text-muted uppercase tracking-wide">{m.api_keys_expires()}</p>
                  <p class="text-sm font-medium text-default mt-0.5 truncate">
                    {key.expires_at ? formatter.format(new Date(key.expires_at)) : m.api_keys_never()}
                  </p>
                </div>
              </div>

              <!-- Rate limit -->
              <div
                class="flex items-start gap-3 p-3 rounded-lg bg-primary/50 border border-default
                       transition-all duration-200 hover:bg-primary hover:border-dimmer"
              >
                <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-subtle border border-dimmer">
                  <Shield class="h-4 w-4 text-muted" />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-xs font-medium text-muted uppercase tracking-wide">{m.api_keys_rate_limit_label()}</p>
                  <p class="text-sm font-medium text-default mt-0.5 truncate">
                    {key.rate_limit ? `${key.rate_limit}/hr` : m.api_keys_default()}
                  </p>
                </div>
              </div>
            </div>

            <!-- Allowed Origins (for pk_ keys) -->
            {#if key.key_type === "pk_" && key.allowed_origins?.length}
              <div class="mt-5 pt-4 border-t border-dimmer">
                <p class="text-xs font-medium text-muted uppercase tracking-wide mb-2.5">{m.api_keys_allowed_origins()}</p>
                <div class="flex flex-wrap gap-2">
                  {#each key.allowed_origins as origin}
                    <span
                      class="inline-flex items-center gap-1.5 rounded-lg bg-primary border border-default
                             px-3 py-1.5 text-xs font-mono text-default
                             transition-all duration-200 hover:border-dimmer hover:bg-subtle"
                    >
                      <Globe class="h-3.5 w-3.5 text-muted" />
                      {origin}
                    </span>
                  {/each}
                </div>
              </div>
            {/if}

            <!-- Allowed IPs (for sk_ keys) -->
            {#if key.key_type === "sk_" && key.allowed_ips?.length}
              <div class="mt-5 pt-4 border-t border-dimmer">
                <p class="text-xs font-medium text-muted uppercase tracking-wide mb-2.5">{m.api_keys_allowed_ips()}</p>
                <div class="flex flex-wrap gap-2">
                  {#each key.allowed_ips as ip}
                    <span
                      class="inline-flex items-center gap-1.5 rounded-lg bg-primary border border-default
                             px-3 py-1.5 text-xs font-mono text-default
                             transition-all duration-200 hover:border-dimmer hover:bg-subtle"
                    >
                      <Server class="h-3.5 w-3.5 text-muted" />
                      {ip}
                    </span>
                  {/each}
                </div>
              </div>
            {/if}

            <!-- Suspension info -->
            {#if key.state === "suspended" && key.suspended_at}
              <div class="mt-5 pt-4 border-t border-dimmer">
                <div
                  class="rounded-lg border border-caution/40 bg-caution/10 p-4
                         dark:border-caution/30 dark:bg-caution/5"
                >
                  <div class="flex items-start gap-3">
                    <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-caution/20">
                      <Shield class="h-4 w-4 text-caution" />
                    </div>
                    <div class="flex-1 min-w-0">
                      <p class="text-sm font-semibold text-caution">{m.api_keys_key_suspended()}</p>
                      <p class="text-sm text-caution/80 mt-1">
                        {formatter.format(new Date(key.suspended_at))}
                      </p>
                      {#if key.suspended_reason_text}
                        <p class="text-sm text-caution/70 mt-2">{key.suspended_reason_text}</p>
                      {/if}
                    </div>
                  </div>
                </div>
              </div>
            {/if}

            <!-- Revocation info -->
            {#if key.state === "revoked" && key.revoked_at}
              <div class="mt-5 pt-4 border-t border-dimmer">
                <div
                  class="rounded-lg border border-negative/40 bg-negative/10 p-4
                         dark:border-negative/30 dark:bg-negative/5"
                >
                  <div class="flex items-start gap-3">
                    <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-negative/20">
                      <Lock class="h-4 w-4 text-negative" />
                    </div>
                    <div class="flex-1 min-w-0">
                      <p class="text-sm font-semibold text-negative">{m.api_keys_key_revoked()}</p>
                      <p class="text-sm text-negative/80 mt-1">
                        {formatter.format(new Date(key.revoked_at))}
                      </p>
                      {#if key.revoked_reason_text}
                        <p class="text-sm text-negative/70 mt-2">{key.revoked_reason_text}</p>
                      {/if}
                    </div>
                  </div>
                </div>
              </div>
            {/if}
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}

<style>
  /* Theme-aware skeleton pulse animation */
  @keyframes skeleton-pulse {
    0%, 100% {
      opacity: 1;
    }
    50% {
      opacity: 0.5;
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
</style>
