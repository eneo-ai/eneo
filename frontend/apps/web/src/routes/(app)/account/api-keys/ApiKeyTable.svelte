<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@eneo/eneo-js";
  import { SvelteSet } from "svelte/reactivity";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { getReasonCodeLabel } from "$lib/features/api-keys/reasonCodeLabel";
  import {
    getScopeStyle,
    getScopeIcon,
    getPermissionStyle,
    getKeyTypeStyle,
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
    Lock,
    Shield,
    Clock,
    Calendar,
    Activity,
    Bell,
    AlertTriangle
  } from "lucide-svelte";
  import { slide } from "svelte/transition";
  import ApiKeyActions from "./ApiKeyActions.svelte";
  import {
    getDaysUntilExpiration,
    getExpiryLevel,
    getEffectiveState
  } from "$lib/features/api-keys/expirationUtils";
  import { useApiKeyUsage } from "$lib/features/api-keys/useApiKeyUsage.svelte";
  import ApiKeyStateBadge from "$lib/features/api-keys/ApiKeyStateBadge.svelte";
  import RotationGraceBadge from "$lib/features/api-keys/RotationGraceBadge.svelte";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  const eneo = getEneo();

  let {
    keys = [],
    loading = false,
    onChanged,
    onSecret,
    followedKeyIds = new Set<string>(),
    scopeFollowed = false,
    onFollowChanged,
    scopeNames = {},
    currentUserId = undefined
  } = $props<{
    keys: ApiKeyV2[];
    loading: boolean;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
    followedKeyIds?: Set<string>;
    scopeFollowed?: boolean;
    onFollowChanged?: () => void | Promise<void>;
    scopeNames?: Record<string, string>;
    currentUserId?: string;
  }>();

  // Track expanded rows (SvelteSet is already reactive — no $state wrapper needed)
  let expandedIds = new SvelteSet<string>();

  const usage = useApiKeyUsage(
    (params) =>
      eneo.apiKeys.getUsage(params) as Promise<
        import("$lib/features/api-keys/apiKeyTableUtils").ApiKeyUsageResponse
      >
  );
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
    if (expandedIds.has(id) && !usage.activeTabByKey[id]) {
      usage.setActiveTab(id, "overview");
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
</script>

{#if loading}
  <!-- Skeleton loader using shadcn Skeleton -->
  <div class="space-y-3" aria-busy="true" aria-live="polite">
    <span class="sr-only">{m.api_keys_admin_usage_loading()}</span>
    {#each Array(3) as _, i (i)}
      <div class="border-default bg-primary rounded-xl border p-4">
        <div class="flex items-center gap-4">
          <Skeleton class="h-11 w-11 rounded-xl" />
          <div class="flex-1 space-y-2.5">
            <Skeleton class="h-4 w-36" />
            <div class="flex gap-2">
              <Skeleton class="h-3 w-24" />
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
      {@const permission = getPermissionStyle(key.permission)}
      {@const PermissionIcon = permission.icon}
      {@const keyTypeStyle = getKeyTypeStyle(key.key_type)}
      {@const KeyIcon = key.key_type === "pk_" ? Globe : Lock}
      {@const daysUntil = getDaysUntilExpiration(key.expires_at)}
      {@const isInactive = effectiveState === "revoked" || effectiveState === "expired"}

      <Collapsible.Root
        open={isExpanded}
        onOpenChange={(open) => {
          if (open !== isExpanded) toggleExpanded(key.id);
        }}
      >
        <Card.Root
          class="gap-0 py-0 transition-all duration-200 hover:-translate-y-px hover:shadow-md
                 {isExpanded
            ? 'ring-accent-default/40 shadow-sm ring-2'
            : 'hover:ring-foreground/20'}
                 {recentlyExpandedId === key.id ? 'animate-expand-pulse' : ''}"
        >
          <!-- Header row: Trigger and ApiKeyActions are siblings (no nested buttons) -->
          <div class="flex items-stretch">
            <Collapsible.Trigger
              class="hover:bg-secondary/30 focus-visible:ring-accent-default/50 group/trigger flex flex-1 items-center gap-4 px-5 py-4 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset
                     {isInactive ? 'opacity-60' : ''}"
            >
              <!-- Key type icon avatar -->
              <div
                class="bg-label-dimmer flex h-11 w-11 shrink-0 items-center justify-center rounded-xl {keyTypeStyle.scopeClass}"
              >
                <KeyIcon class="text-label-stronger h-5 w-5" />
              </div>

              <!-- Key info -->
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span class="flex items-center gap-1.5">
                    <h4 class="text-default truncate font-semibold">{key.name}</h4>
                    {#if followedKeyIds.has(key.id)}
                      <Bell class="text-accent-default h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                    {/if}
                  </span>

                  <ApiKeyStateBadge state={effectiveState} />
                </div>

                <!-- Key preview + scope/permission/service badges -->
                <div class="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
                  <code
                    class="text-muted bg-secondary inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-xs"
                  >
                    {key.key_type}<span class="opacity-30">····</span>{key.key_suffix}
                  </code>

                  <!-- Scope badge: outline + icon, no saturated background -->
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

                  <!-- Service key badge -->
                  {#if key.ownership === "service"}
                    <Badge
                      variant="outline"
                      class="text-muted h-auto gap-1.5 px-2 py-0.5"
                      title={m.api_keys_ownership_service_badge_tooltip()}
                    >
                      <Server class="h-3 w-3" />
                      {m.api_keys_ownership_service_badge()}
                    </Badge>
                  {/if}

                  <!-- Rotation grace period indicator -->
                  {#if key.rotation_grace_until}
                    <RotationGraceBadge graceUntil={key.rotation_grace_until} />
                  {/if}
                </div>
              </div>

              <!-- Right side info (hidden on mobile) -->
              <div
                class="hidden items-center gap-6 text-sm sm:flex"
                style="font-variant-numeric: tabular-nums"
              >
                <!-- Expiration -->
                {#if daysUntil !== null}
                  {@const expiryLevel = getExpiryLevel(daysUntil)}
                  <div class="flex items-center gap-1.5 text-right">
                    {#if expiryLevel === "urgent" || expiryLevel === "expired"}
                      <span
                        class="bg-destructive h-1.5 w-1.5 flex-shrink-0 rounded-full"
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
                          ? 'text-destructive'
                          : expiryLevel === 'warning' || expiryLevel === 'notice'
                            ? 'text-warning-stronger'
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
                  <p class="text-default font-medium">{fmtRelDate(key.last_used_at)}</p>
                </div>
              </div>

              <!-- Chevron rotates with collapsible state -->
              <ChevronDown
                class="text-muted size-4 shrink-0 transition-transform duration-200 group-data-[state=open]/trigger:rotate-180"
              />
            </Collapsible.Trigger>

            <!-- Action menu sits OUTSIDE the trigger as a sibling — no nested buttons -->
            <div class="flex items-center pr-3">
              <ApiKeyActions
                apiKey={key}
                {onChanged}
                {onSecret}
                isFollowed={followedKeyIds?.has(key.id) ?? false}
                isFollowedViaScope={scopeFollowed && !(followedKeyIds?.has(key.id) ?? false)}
                {onFollowChanged}
                {currentUserId}
              />
            </div>
          </div>

          <!-- Expanded details -->
          <Collapsible.Content>
            <div
              id="details-{key.id}"
              class="border-border from-secondary/40 to-secondary/20 border-t bg-gradient-to-b px-5 py-5"
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
                        <div class="bg-primary/50 border-default rounded-lg border p-3">
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
                        <div class="bg-primary/50 border-default rounded-lg border p-3">
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
                        <div class="bg-primary/50 border-default rounded-lg border p-3">
                          <p class="text-muted text-xs">{m.api_keys_admin_usage_failed_events()}</p>
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
                        <div class="bg-primary/50 border-default rounded-lg border p-3">
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
                                      <Badge
                                        variant={event.action === "api_key_auth_failed"
                                          ? "destructive"
                                          : "secondary"}
                                      >
                                        {event.action}
                                      </Badge>
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
                    {/if}
                  </div>
                </Tabs.Content>

                <Tabs.Content value="overview">
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
                        class="border-negative-default/40 bg-negative-default/10 dark:border-negative-default/30 dark:bg-negative-default/5 rounded-lg
                           border p-4"
                      >
                        <div class="flex items-start gap-3">
                          <div
                            class="bg-negative-default/20 flex h-8 w-8 items-center justify-center rounded-lg"
                          >
                            <Lock class="text-negative-stronger h-4 w-4" />
                          </div>
                          <div class="min-w-0 flex-1">
                            <p class="text-negative-stronger text-sm font-semibold">
                              {m.api_keys_key_revoked()}
                            </p>
                            <p class="text-negative-stronger/80 mt-1 text-sm">
                              {formatter.format(new Date(key.revoked_at))}
                            </p>
                            {#if revokedReasonLabel}
                              <p class="text-negative-stronger/70 mt-2 text-sm">
                                {revokedReasonLabel}
                              </p>
                            {/if}
                            {#if key.revoked_reason_text}
                              <p class="text-negative-stronger/60 mt-1 text-xs">
                                {key.revoked_reason_text}
                              </p>
                            {/if}
                          </div>
                        </div>
                      </div>
                    </div>
                  {/if}
                </Tabs.Content>
              </Tabs.Root>
            </div>
          </Collapsible.Content>
        </Card.Root>
      </Collapsible.Root>
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
      box-shadow: 0 0 0 0 oklch(from var(--color-accent-default) l c h / 0.4);
    }
    70% {
      box-shadow: 0 0 0 8px oklch(from var(--color-accent-default) l c h / 0);
    }
    100% {
      box-shadow: 0 0 0 0 oklch(from var(--color-accent-default) l c h / 0);
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
