<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
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
  import { SvelteSet, SvelteURLSearchParams } from "svelte/reactivity";
  import {
    getDaysUntilExpiration,
    getExpiryLevel,
    getEffectiveState
  } from "$lib/features/api-keys/expirationUtils";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

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

  // Track expanded rows (SvelteSet is already reactive — no $state wrapper needed)
  let expandedIds = new SvelteSet<string>();
  let activeTabByKey = $state<Record<string, "overview" | "usage">>({});
  let usageByKey = $state<Record<string, ApiKeyUsageResponse>>({});
  let usageErrorByKey = $state<Record<string, string | null>>({});
  let usageLoadingByKey = $state<Record<string, boolean>>({});
  let usageCursorByKey = $state<Record<string, string | null>>({});

  function toggleExpanded(id: string, open: boolean) {
    if (open) {
      expandedIds.add(id);
      if (!activeTabByKey[id]) {
        activeTabByKey = { ...activeTabByKey, [id]: "overview" };
      }
    } else {
      expandedIds.delete(id);
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

  // The scope_id field is meaningful only for non-tenant scopes; we relabel it per type so a
  // reader sees "Assistant ID" / "App ID" / "Space ID" instead of the abstract "Scope ID".
  // Falls back to the generic label if the backend ever sends an unknown scope_type.
  function getScopeIdLabel(scopeType: string | null | undefined): string {
    switch (scopeType) {
      case "space":
        return m.api_keys_admin_scope_id_label_space();
      case "assistant":
        return m.api_keys_admin_scope_id_label_assistant();
      case "app":
        return m.api_keys_admin_scope_id_label_app();
      default:
        return m.api_keys_admin_scope_id_label();
    }
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
        [id]: getErrorMessage(error)
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

  // Scope/state/permission/key-type configs use eneo's semantic tokens.
  // Raw `blue/green/purple/orange/red/yellow-*` palette utilities resolve
  // to Tailwind v4 oklch() values that Chrome and Firefox gamut-map
  // differently; the `*-default`/`*-stronger`/`*-dimmer` tokens below are
  // single CSS variable lookups that render identically across browsers
  // and switch automatically between light and dark themes. Scope badges
  // use neutral outline styling (matching ApiKeyTable) so the icon — not
  // colour — conveys the scope type, freeing the colour palette for
  // status / permission semantics that benefit more from saturation.
  const scopeConfig = $derived<
    Record<string, { label: string; icon: typeof Building2; color: string }>
  >({
    tenant: {
      label: m.api_keys_admin_scope_tenant(),
      icon: Building2,
      color: "border border-default text-muted"
    },
    space: {
      label: m.api_keys_admin_scope_space(),
      icon: Building2,
      color: "border border-default text-muted"
    },
    assistant: {
      label: m.api_keys_admin_scope_assistant(),
      icon: MessageSquare,
      color: "border border-default text-muted"
    },
    app: {
      label: m.api_keys_admin_scope_app(),
      icon: AppWindow,
      color: "border border-default text-muted"
    }
  });

  const stateConfig = $derived<Record<string, { label: string; dotColor: string }>>({
    active: {
      label: m.api_keys_admin_state_active(),
      dotColor: "bg-positive-default"
    },
    suspended: {
      label: m.api_keys_admin_state_suspended(),
      dotColor: "bg-warning-default"
    },
    revoked: {
      label: m.api_keys_admin_state_revoked(),
      dotColor: "bg-negative-default"
    },
    expired: {
      label: m.api_keys_admin_state_expired(),
      dotColor: "bg-tertiary"
    }
  });

  const permissionConfig: Record<string, { label: string; color: string; icon: typeof Eye }> = {
    read: {
      label: m.api_keys_permission_read(),
      color: "bg-secondary/60 text-muted border border-default",
      icon: Eye
    },
    write: {
      label: m.api_keys_permission_write(),
      color:
        "text-warning-stronger border border-warning-default/40 bg-warning-dimmer/40 dark:bg-warning-dimmer/20",
      icon: Pencil
    },
    admin: {
      label: m.api_keys_permission_admin(),
      color: "text-negative-stronger border border-negative-default/40 bg-negative-default/10",
      icon: ShieldCheck
    }
  };

  // Key-type avatar uses eneo's `label-*` scope system so colours match
  // ApiKeyTable: amethyst for `pk_`, blue for `sk_`. The parent scope class
  // sets `--color-label-stronger/dimmer`, which the inner `bg-label-dimmer`
  // / `text-label-stronger` utilities resolve against — flat CSS variable
  // lookups, no color-mix() opacity expansion.
  function getKeyTypeConfig(keyType: string) {
    return keyType === "pk_"
      ? {
          label: m.api_keys_admin_key_type_public_label(),
          icon: Globe,
          scopeClass: "label-amethyst"
        }
      : {
          label: m.api_keys_admin_key_type_secret_label(),
          icon: Lock,
          scopeClass: "label-blue"
        };
  }

  function openAuditLogsForKey(key: AdminApiKey): string {
    const params = new SvelteURLSearchParams();
    params.set("tab", "logs");
    params.set("search", key.key_suffix);
    params.set("actions", "api_key_used,api_key_auth_failed");
    return `/admin/audit-logs?${params.toString()}`;
  }
</script>

{#if loading}
  <!-- Skeleton loader using shadcn Skeleton -->
  <div class="space-y-3" aria-busy="true" aria-live="polite">
    <span class="sr-only">{m.api_keys_admin_usage_loading()}</span>
    {#each Array(5) as _, i (i)}
      <div class="border-default bg-primary rounded-xl border p-4">
        <div class="flex items-center gap-4">
          <Skeleton class="h-11 w-11 rounded-xl" />
          <div class="flex-1 space-y-2.5">
            <Skeleton class="h-4 w-40" />
            <div class="flex gap-2">
              <Skeleton class="h-3 w-28" />
              <Skeleton class="h-3 w-16" />
            </div>
          </div>
          <div class="hidden items-center gap-4 sm:flex">
            <Skeleton class="h-8 w-20" />
            <Skeleton class="h-8 w-20" />
          </div>
          <Skeleton class="h-8 w-8 rounded-lg" />
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
      {@const effectiveState = getEffectiveState(key)}
      {@const state = stateConfig[effectiveState] ?? stateConfig.active}
      {@const permission = permissionConfig[key.permission] ?? permissionConfig.read}
      {@const keyTypeConf = getKeyTypeConfig(key.key_type)}
      {@const daysUntil = getDaysUntilExpiration(key.expires_at)}
      {@const KeyTypeIcon = keyTypeConf.icon}
      {@const ScopeIcon = scope.icon}
      {@const PermissionIcon = permission.icon}
      {@const isInactive = effectiveState === "revoked" || effectiveState === "expired"}

      <Collapsible.Root open={isExpanded} onOpenChange={(open) => toggleExpanded(key.id, open)}>
        <Card.Root
          class="gap-0 py-0 transition-all duration-200 hover:-translate-y-px hover:shadow-md
                 {isExpanded
            ? 'ring-accent-default/40 shadow-sm ring-2'
            : 'hover:ring-foreground/20'}"
        >
          <!-- Header row: Trigger and AdminApiKeyActions are siblings (no nested buttons) -->
          <div class="flex items-stretch">
            <Collapsible.Trigger
              class="hover:bg-secondary/30 focus-visible:ring-accent-default/50 group/trigger flex flex-1 items-center gap-4 px-5 py-4 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset
                     {isInactive ? 'opacity-60' : ''}"
            >
              <!-- Key type icon avatar -->
              <div
                class="bg-label-dimmer flex h-11 w-11 shrink-0 items-center justify-center rounded-xl {keyTypeConf.scopeClass}"
              >
                <KeyTypeIcon class="text-label-stronger h-5 w-5" />
              </div>

              <!-- Key info -->
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <h4 class="text-default truncate font-semibold">{key.name}</h4>

                  <!-- Status dot + label with accessible tooltip -->
                  <Tooltip.Provider delayDuration={150}>
                    <Tooltip.Root>
                      <Tooltip.Trigger>
                        {#snippet child({ props })}
                          <span {...props} class="flex items-center gap-1.5">
                            <span
                              class="h-2.5 w-2.5 rounded-full {state.dotColor}"
                              aria-hidden="true"
                            ></span>
                            <span class="text-muted text-xs">{state.label}</span>
                            <span class="sr-only">{getStatusTooltip(effectiveState)}</span>
                          </span>
                        {/snippet}
                      </Tooltip.Trigger>
                      <Tooltip.Content>
                        {getStatusTooltip(effectiveState)}
                      </Tooltip.Content>
                    </Tooltip.Root>
                  </Tooltip.Provider>
                </div>

                <!-- Key preview + scope/permission/key-type badges -->
                <div class="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
                  <code
                    class="text-muted bg-secondary inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-xs"
                  >
                    {key.key_type}<span class="opacity-30">····</span>{key.key_suffix}
                  </code>

                  <!-- Scope badge -->
                  <Badge variant="outline" class="text-muted h-auto gap-1.5 px-2 py-0.5">
                    <ScopeIcon class="h-3 w-3" />
                    {scope.label}
                    {#if key.scope_id}
                      <span class="text-muted/70" aria-hidden="true">·</span>
                      <span class="font-mono"
                        >{scopeNames[key.scope_id] ?? key.scope_id.slice(0, 8)}</span
                      >
                    {/if}
                  </Badge>

                  <!-- Permission badge: semantic color tint per level (read=neutral, write=warning, admin=danger) -->
                  <Badge
                    variant="outline"
                    class="h-auto gap-1.5 px-2 py-0.5 font-semibold {permission.color}"
                  >
                    <PermissionIcon class="h-3 w-3" />
                    {permission.label}
                  </Badge>

                  <!-- Key type badge -->
                  <Badge variant="outline" class="text-muted h-auto gap-1.5 px-2 py-0.5">
                    <KeyTypeIcon class="h-3 w-3" />
                    {keyTypeConf.label}
                  </Badge>
                </div>

                <!-- Owner + match reasons meta -->
                <div class="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  <span class="text-muted inline-flex items-center gap-1.5">
                    <User class="h-3.5 w-3.5" />
                    {m.api_keys_admin_owner_label()}:
                    <span class="text-default font-medium">
                      {getIdentityLabel(key.owner_user, key.owner_user_id)}
                    </span>
                  </span>
                  {#if key.search_match_reasons?.length}
                    {#each key.search_match_reasons as reason (reason)}
                      <Badge
                        variant="outline"
                        class="bg-accent-default/10 text-accent-default border-accent-default/30 h-auto px-1.5 py-0.5 text-[11px] font-medium"
                      >
                        {getMatchReasonLabel(reason)}
                      </Badge>
                    {/each}
                  {/if}
                </div>
              </div>

              <!-- Right side info (hidden on mobile) -->
              <div
                class="hidden items-center text-sm lg:flex"
                style="font-variant-numeric: tabular-nums"
              >
                <!-- Rate limit -->
                <div class="border-default/50 border-l px-4 text-right first:border-l-0 first:pl-0">
                  <p class="text-muted text-xs">{m.api_keys_admin_rate_limit()}</p>
                  <p class="text-default font-medium">
                    {key.rate_limit
                      ? m.api_keys_rate_limit_value({ count: key.rate_limit })
                      : m.api_keys_default()}
                  </p>
                </div>

                <!-- Expiration -->
                {#if daysUntil !== null}
                  {@const expiryLevel = getExpiryLevel(daysUntil)}
                  <div
                    class="border-default/50 flex items-center gap-1.5 border-l px-4 text-right first:border-l-0 first:pl-0"
                  >
                    {#if expiryLevel === "urgent" || expiryLevel === "expired"}
                      <span
                        class="bg-negative-default h-1.5 w-1.5 flex-shrink-0 rounded-full"
                        aria-hidden="true"
                      ></span>
                    {:else if expiryLevel === "warning"}
                      <span
                        class="bg-warning-default h-1.5 w-1.5 flex-shrink-0 rounded-full"
                        aria-hidden="true"
                      ></span>
                    {/if}
                    <div>
                      <p class="text-muted text-xs">{m.api_keys_expires()}</p>
                      <p
                        class="font-medium {expiryLevel === 'expired' || expiryLevel === 'urgent'
                          ? 'text-negative-stronger'
                          : expiryLevel === 'warning' || expiryLevel === 'notice'
                            ? 'text-warning-stronger'
                            : 'text-default'}"
                      >
                        {daysUntil < 0
                          ? m.api_keys_admin_expired_label()
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
                <div class="border-default/50 border-l pl-4 text-right first:border-l-0 first:pl-0">
                  <p class="text-muted text-xs">{m.api_keys_last_used()}</p>
                  <p class="text-default font-medium">{formatRelativeDate(key.last_used_at)}</p>
                </div>
              </div>

              <!-- Chevron rotates with collapsible state -->
              <ChevronDown
                class="text-muted ml-2 size-4 shrink-0 transition-transform duration-200 group-data-[state=open]/trigger:rotate-180"
              />
            </Collapsible.Trigger>

            <!-- Action menu sits OUTSIDE the trigger as a sibling — no nested buttons -->
            <div class="flex items-center pr-3">
              <AdminApiKeyActions apiKey={key} {onChanged} {onSecret} />
            </div>
          </div>

          <!-- Expanded details -->
          <Collapsible.Content>
            <div
              id={"admin-api-key-details-" + key.id}
              class="border-default bg-subtle/50 border-t px-5 py-4"
              transition:slide={{ duration: 200 }}
            >
              <Tabs.Root
                value={activeTabByKey[key.id] ?? "overview"}
                onValueChange={(v) => setActiveTab(key.id, v as "overview" | "usage")}
              >
                <Tabs.List class="mb-4">
                  <Tabs.Trigger value="overview">{m.api_keys_admin_tab_overview()}</Tabs.Trigger>
                  <Tabs.Trigger value="usage">{m.api_keys_admin_tab_usage()}</Tabs.Trigger>
                </Tabs.List>

                <Tabs.Content value="usage">
                  {@const usage = usageByKey[key.id]}
                  <div class="space-y-4">
                    {#if usageLoadingByKey[key.id]}
                      <div class="text-muted text-sm">{m.api_keys_admin_usage_loading()}</div>
                    {:else if usageErrorByKey[key.id]}
                      <div class="text-negative-stronger text-sm">{usageErrorByKey[key.id]}</div>
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
                          <p class="text-muted text-xs">
                            {m.api_keys_admin_usage_success_events()}
                          </p>
                          <p
                            class="{(usage?.summary?.used_events ?? 0) > 0
                              ? 'text-positive-stronger'
                              : 'text-default'} mt-1 text-lg font-semibold tabular-nums"
                            title={fullNumberFormatter.format(usage?.summary?.used_events ?? 0)}
                          >
                            {formatUsageMetric(usage?.summary?.used_events)}
                          </p>
                        </div>
                        <div class="bg-primary border-default rounded-lg border p-3">
                          <p class="text-muted text-xs">
                            {m.api_keys_admin_usage_failed_events()}
                          </p>
                          <p
                            class="{(usage?.summary?.auth_failed_events ?? 0) > 0
                              ? 'text-negative-stronger'
                              : 'text-default'} mt-1 text-lg font-semibold tabular-nums"
                            title={fullNumberFormatter.format(
                              usage?.summary?.auth_failed_events ?? 0
                            )}
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
                          class="border-warning-default/40 bg-warning-dimmer/40 text-warning-stronger dark:bg-warning-dimmer/20 rounded-lg border p-3 text-xs"
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
                            <Table.Root>
                              <Table.Caption class="sr-only">
                                {m.api_keys_admin_tab_usage()}
                              </Table.Caption>
                              <Table.Header class="bg-subtle/80 sticky top-0 z-10">
                                <Table.Row>
                                  <Table.Head>{m.audit_timestamp()}</Table.Head>
                                  <Table.Head>{m.audit_action()}</Table.Head>
                                  <Table.Head>{m.api_keys_admin_usage_request()}</Table.Head>
                                  <Table.Head>{m.api_keys_admin_usage_ip_origin()}</Table.Head>
                                </Table.Row>
                              </Table.Header>
                              <Table.Body>
                                {#each usage.items as event (event.id)}
                                  <Table.Row>
                                    <Table.Cell
                                      class="text-muted text-xs whitespace-nowrap tabular-nums"
                                    >
                                      {formatter.format(new Date(event.timestamp))}
                                    </Table.Cell>
                                    <Table.Cell>
                                      <span
                                        class="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium {event.action ===
                                        'api_key_auth_failed'
                                          ? 'bg-negative-default/15 text-negative-stronger'
                                          : 'bg-positive-default/15 text-positive-stronger'}"
                                      >
                                        {event.action}
                                      </span>
                                    </Table.Cell>
                                    <Table.Cell class="text-muted text-xs">
                                      <div class="flex items-center gap-1.5">
                                        <span class="shrink-0 font-medium">
                                          {event.method ?? "—"}
                                        </span>
                                        {#if event.request_path}
                                          <span class="text-muted/60" aria-hidden="true">·</span>
                                          <span
                                            class="max-w-[24rem] truncate font-mono"
                                            title={event.request_path}
                                          >
                                            {event.request_path}
                                          </span>
                                        {/if}
                                      </div>
                                    </Table.Cell>
                                    <Table.Cell class="text-muted text-xs">
                                      <div class="flex items-center gap-1.5">
                                        <span class="shrink-0 font-mono">
                                          {event.ip_address ?? "—"}
                                        </span>
                                        {#if event.origin}
                                          <span class="text-muted/60" aria-hidden="true">·</span>
                                          <span class="max-w-[18rem] truncate" title={event.origin}>
                                            {event.origin}
                                          </span>
                                        {/if}
                                      </div>
                                    </Table.Cell>
                                  </Table.Row>
                                {/each}
                              </Table.Body>
                            </Table.Root>
                          </div>
                        </div>
                      {:else}
                        <div class="text-muted text-sm">{m.api_keys_admin_usage_empty()}</div>
                      {/if}

                      {#if usageCursorByKey[key.id]}
                        <Button variant="outline" size="sm" onclick={() => loadMoreUsage(key.id)}>
                          {m.api_keys_admin_usage_load_more()}
                        </Button>
                      {/if}

                      <!-- eslint-disable svelte/no-navigation-without-resolve -- dynamic query string -->
                      <a
                        href={openAuditLogsForKey(key)}
                        class="text-accent-default hover:text-accent-default/80 inline-flex items-center gap-1.5 text-xs font-medium"
                      >
                        <Link class="h-3.5 w-3.5" />
                        {m.api_keys_admin_usage_open_audit_logs()}
                      </a>
                      <!-- eslint-enable svelte/no-navigation-without-resolve -->
                    {/if}
                  </div>
                </Tabs.Content>

                <Tabs.Content value="overview">
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
                          <!-- eslint-disable svelte/no-navigation-without-resolve -- dynamic query string -->
                          <a
                            href={`/admin/users?tab=active&search=${encodeURIComponent(key.owner_user.email)}`}
                            class="text-accent-default hover:text-accent-default/80 mt-1 inline-flex items-center gap-1 text-xs font-medium"
                          >
                            <Link class="h-3 w-3" />
                            {m.api_keys_admin_view_user()}
                          </a>
                          <!-- eslint-enable svelte/no-navigation-without-resolve -->
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
                          {key.rate_limit
                            ? m.api_keys_rate_limit_value({ count: key.rate_limit })
                            : m.api_keys_default()}
                        </p>
                      </div>
                    </div>

                    {#if key.scope_id}
                      {@const ScopeIdIcon = scopeConfig[key.scope_type]?.icon ?? Building2}
                      <div class="flex items-start gap-3 sm:col-span-2">
                        <div class="bg-primary flex h-9 w-9 items-center justify-center rounded-lg">
                          <ScopeIdIcon class="text-muted h-4 w-4" />
                        </div>
                        <div class="min-w-0 flex-1">
                          <p class="text-muted text-xs">{getScopeIdLabel(key.scope_type)}</p>
                          {#if scopeNames[key.scope_id]}
                            <p class="text-default text-sm font-medium">
                              {scopeNames[key.scope_id]}
                            </p>
                          {/if}
                          <code
                            class="bg-primary border-default text-default mt-1.5 inline-block rounded-md border px-3 py-1.5 font-mono text-xs"
                          >
                            {key.scope_id}
                          </code>
                        </div>
                      </div>
                    {/if}

                    {#if key.key_type === "pk_" && key.allowed_origins?.length}
                      <div class="sm:col-span-2">
                        <p class="text-muted mb-2 text-xs">
                          {m.api_keys_admin_allowed_origins_label()}
                        </p>
                        <div class="flex flex-wrap gap-1.5">
                          {#each key.allowed_origins as origin (origin)}
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
                        <p class="text-muted mb-2 text-xs">
                          {m.api_keys_admin_allowed_ips_label()}
                        </p>
                        <div class="flex flex-wrap gap-1.5">
                          {#each key.allowed_ips as ip (ip)}
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
                </Tabs.Content>
              </Tabs.Root>
            </div>
          </Collapsible.Content>
        </Card.Root>
      </Collapsible.Root>
    {/each}
  </div>
{/if}
