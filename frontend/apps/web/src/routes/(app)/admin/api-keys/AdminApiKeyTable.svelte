<script lang="ts">
  import type { ApiKeyCreatedResponse } from "@eneo/eneo-js";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import {
    type AdminApiKey,
    getPermissionStyle,
    getKeyTypeConfig,
    getScopeConfig,
    createDateFormatter,
    createRelativeFormatter,
    createFullNumberFormatter,
    createCompactNumberFormatter,
    formatUsageMetric,
    formatRelativeDate
  } from "$lib/features/api-keys/apiKeyTableUtils";
  import {
    ChevronDown,
    Key,
    Globe,
    Server,
    Shield,
    Clock,
    Calendar,
    Activity,
    User,
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
  import { useApiKeyUsage } from "$lib/features/api-keys/useApiKeyUsage.svelte";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  const eneo = getEneo();
  import AdminApiKeyActions from "./AdminApiKeyActions.svelte";
  import ApiKeyStateBadge from "$lib/features/api-keys/ApiKeyStateBadge.svelte";
  import RotationGraceBadge from "$lib/features/api-keys/RotationGraceBadge.svelte";

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

  const usage = useApiKeyUsage(
    (params) =>
      eneo.apiKeys.admin.getUsage(params) as Promise<
        import("$lib/features/api-keys/apiKeyTableUtils").ApiKeyUsageResponse
      >
  );
  function toggleExpanded(id: string, open: boolean) {
    if (open) {
      expandedIds.add(id);
      if (!usage.activeTabByKey[id]) {
        usage.setActiveTab(id, "overview");
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

  // Locale-aware formatters (delegated to shared utils)
  const formatter = createDateFormatter();
  const relativeFormatter = createRelativeFormatter();
  const fullNumberFormatter = createFullNumberFormatter();
  const compactNumberFormatter = createCompactNumberFormatter();

  function fmtUsage(value: number | null | undefined): string {
    return formatUsageMetric(compactNumberFormatter, value);
  }

  function fmtRelDate(date: string | null | undefined): string {
    return formatRelativeDate(formatter, relativeFormatter, date);
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
      {@const scope = getScopeConfig(key.scope_type)}
      {@const effectiveState = getEffectiveState(key)}
      {@const permission = getPermissionStyle(key.permission)}
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

                  <ApiKeyStateBadge state={effectiveState} />
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
                    class="h-auto gap-1.5 px-2 py-0.5 font-semibold {permission.badgeClass}"
                  >
                    <PermissionIcon class="h-3 w-3" />
                    {permission.label}
                  </Badge>

                  <!-- Key type badge -->
                  <Badge variant="outline" class="text-muted h-auto gap-1.5 px-2 py-0.5">
                    <KeyTypeIcon class="h-3 w-3" />
                    {keyTypeConf.label}
                  </Badge>

                  <!-- Rotation grace period indicator -->
                  {#if key.rotation_grace_until}
                    <RotationGraceBadge graceUntil={key.rotation_grace_until} />
                  {/if}
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
                  <p class="text-default font-medium">{fmtRelDate(key.last_used_at)}</p>
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
                value={usage.activeTabByKey[key.id] ?? "overview"}
                onValueChange={(v) => usage.setActiveTab(key.id, v as "overview" | "usage")}
              >
                <Tabs.List class="mb-4">
                  <Tabs.Trigger value="overview">{m.api_keys_admin_tab_overview()}</Tabs.Trigger>
                  <Tabs.Trigger value="usage">{m.api_keys_admin_tab_usage()}</Tabs.Trigger>
                </Tabs.List>

                <Tabs.Content value="usage">
                  {@const usageData = usage.usageByKey[key.id]}
                  <div class="space-y-4">
                    {#if usage.usageLoadingByKey[key.id]}
                      <div class="text-muted text-sm">{m.api_keys_admin_usage_loading()}</div>
                    {:else if usage.usageErrorByKey[key.id]}
                      <div class="text-negative-stronger text-sm">
                        {usage.usageErrorByKey[key.id]}
                      </div>
                    {:else}
                      <div class="grid gap-3 md:grid-cols-4">
                        <div class="bg-primary border-default rounded-lg border p-3">
                          <p class="text-muted text-xs">{m.api_keys_admin_usage_total_events()}</p>
                          <p
                            class="text-default mt-1 text-lg font-semibold tabular-nums"
                            title={fullNumberFormatter.format(
                              usageData?.summary?.total_events ?? 0
                            )}
                          >
                            {fmtUsage(usageData?.summary?.total_events)}
                          </p>
                        </div>
                        <div class="bg-primary border-default rounded-lg border p-3">
                          <p class="text-muted text-xs">
                            {m.api_keys_admin_usage_success_events()}
                          </p>
                          <p
                            class="{(usageData?.summary?.used_events ?? 0) > 0
                              ? 'text-positive-stronger'
                              : 'text-default'} mt-1 text-lg font-semibold tabular-nums"
                            title={fullNumberFormatter.format(usageData?.summary?.used_events ?? 0)}
                          >
                            {fmtUsage(usageData?.summary?.used_events)}
                          </p>
                        </div>
                        <div class="bg-primary border-default rounded-lg border p-3">
                          <p class="text-muted text-xs">
                            {m.api_keys_admin_usage_failed_events()}
                          </p>
                          <p
                            class="{(usageData?.summary?.auth_failed_events ?? 0) > 0
                              ? 'text-negative-stronger'
                              : 'text-default'} mt-1 text-lg font-semibold tabular-nums"
                            title={fullNumberFormatter.format(
                              usageData?.summary?.auth_failed_events ?? 0
                            )}
                          >
                            {fmtUsage(usageData?.summary?.auth_failed_events)}
                          </p>
                        </div>
                        <div class="bg-primary border-default rounded-lg border p-3">
                          <p class="text-muted text-xs">{m.api_keys_last_used()}</p>
                          <p class="text-default mt-1 text-sm font-semibold">
                            {usageData?.summary?.last_seen_at
                              ? formatter.format(new Date(usageData.summary.last_seen_at))
                              : m.api_keys_never()}
                          </p>
                        </div>
                      </div>

                      {#if usageData?.summary?.sampled_used_events}
                        <div
                          class="border-warning-default/40 bg-warning-dimmer/40 text-warning-stronger dark:bg-warning-dimmer/20 rounded-lg border p-3 text-xs"
                        >
                          <span class="inline-flex items-center gap-1.5">
                            <AlertTriangle class="h-3.5 w-3.5" />
                            {m.api_keys_admin_usage_sampled_notice()}
                          </span>
                        </div>
                      {/if}

                      {#if usageData?.items?.length}
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
                                {#each usageData.items as event (event.id)}
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

                      {#if usage.usageCursorByKey[key.id]}
                        <Button
                          variant="outline"
                          size="sm"
                          onclick={() => usage.loadMoreUsage(key.id)}
                        >
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
                      {@const ScopeIdIcon = getScopeConfig(key.scope_type).icon}
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
