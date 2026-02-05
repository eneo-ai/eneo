<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import { Button, Label } from "@intric/ui";
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
    ShieldCheck
  } from "lucide-svelte";
  import { slide, fly } from "svelte/transition";
  import AdminApiKeyActions from "./AdminApiKeyActions.svelte";

  let {
    keys = [],
    loading = false,
    scopeNames = {},
    onChanged,
    onSecret
  } = $props<{
    keys: ApiKeyV2[];
    loading: boolean;
    scopeNames?: Record<string, string>;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
  }>();

  // Track expanded rows
  let expandedIds = $state<Set<string>>(new Set());

  function toggleExpanded(id: string) {
    if (expandedIds.has(id)) {
      expandedIds.delete(id);
    } else {
      expandedIds.add(id);
    }
    expandedIds = new Set(expandedIds);
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

  const permissionConfig: Record<string, { color: string; icon: typeof Eye }> = {
    read: { color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300", icon: Eye },
    write: {
      color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
      icon: Pencil
    },
    admin: {
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
        <button
          type="button"
          onclick={() => toggleExpanded(key.id)}
          aria-expanded={isExpanded}
          aria-controls={"admin-api-key-details-" + key.id}
          class="w-full px-5 py-4 text-left"
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
                  {key.permission}
                </span>
              </div>
            </div>

            <!-- Right side info -->
            <div class="hidden items-center gap-6 text-sm lg:flex">
              <!-- Rate limit -->
              <div class="text-right">
                <p class="text-muted text-xs">{m.api_keys_admin_rate_limit()}</p>
                <p class="text-default font-medium">
                  {key.rate_limit ? `${key.rate_limit}/hr` : m.api_keys_default()}
                </p>
              </div>

              <!-- Expiration -->
              {#if daysUntil !== null}
                <div class="text-right">
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
              <div class="text-right">
                <p class="text-muted text-xs">{m.api_keys_last_used()}</p>
                <p class="text-default font-medium">{formatRelativeDate(key.last_used_at)}</p>
              </div>
            </div>

            <!-- Actions and expand -->
            <div class="flex items-center gap-2">
              <AdminApiKeyActions apiKey={key} {onChanged} {onSecret} />

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
        </button>

        <!-- Expanded details -->
        {#if isExpanded}
          <div
            id={"admin-api-key-details-" + key.id}
            role="region"
            aria-label={"API key details for " + key.name}
            class="border-default bg-subtle/50 border-t px-5 py-4"
            transition:slide={{ duration: 200 }}
          >
            <div class="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              <!-- Description -->
              {#if key.description}
                <div class="sm:col-span-2 lg:col-span-4">
                  <p class="text-muted text-sm">{key.description}</p>
                </div>
              {/if}

              <!-- Creator (admin-specific) -->
              {#if key.created_by_user_id}
                <div class="flex items-start gap-3">
                  <div class="bg-primary flex h-9 w-9 items-center justify-center rounded-lg">
                    <User class="text-muted h-4 w-4" />
                  </div>
                  <div>
                    <p class="text-muted text-xs">{m.api_keys_admin_created_by_label()}</p>
                    <p
                      class="text-default max-w-[180px] truncate font-mono text-sm"
                      title={key.created_by_user_id}
                    >
                      {key.created_by_user_id.slice(0, 8)}...
                    </p>
                  </div>
                </div>
              {/if}

              <!-- Created -->
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

              <!-- Last used -->
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

              <!-- Expires -->
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

              <!-- Rate limit -->
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

              <!-- Full Scope ID -->
              {#if key.scope_id}
                <div class="sm:col-span-2">
                  <p class="text-muted mb-2 text-xs">{m.api_keys_admin_scope_id_label()}</p>
                  {#if scopeNames[key.scope_id]}
                    <p class="text-default mb-2 text-sm font-medium">{scopeNames[key.scope_id]}</p>
                  {/if}
                  <code
                    class="bg-primary border-default text-default inline-block rounded-md border px-3 py-1.5 font-mono text-xs"
                  >
                    {key.scope_id}
                  </code>
                </div>
              {/if}

              <!-- Allowed Origins (for pk_ keys) -->
              {#if key.key_type === "pk_" && key.allowed_origins?.length}
                <div class="sm:col-span-2">
                  <p class="text-muted mb-2 text-xs">{m.api_keys_admin_allowed_origins_label()}</p>
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

              <!-- Allowed IPs (for sk_ keys) -->
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

              <!-- Suspension info -->
              {#if key.state === "suspended" && key.suspended_at}
                <div class="sm:col-span-2 lg:col-span-4">
                  <div
                    class="rounded-lg border border-yellow-200 bg-yellow-50 p-3 dark:border-yellow-800 dark:bg-yellow-900/20"
                  >
                    <p class="text-sm text-yellow-700 dark:text-yellow-300">
                      <strong>{m.api_keys_admin_suspended_label()}</strong>
                      {formatter.format(new Date(key.suspended_at))}
                      {#if key.suspended_reason_text}
                        <br /><span class="text-yellow-600 dark:text-yellow-400"
                          >{key.suspended_reason_text}</span
                        >
                      {/if}
                    </p>
                  </div>
                </div>
              {/if}

              <!-- Revocation info -->
              {#if key.state === "revoked" && key.revoked_at}
                <div class="sm:col-span-2 lg:col-span-4">
                  <div
                    class="rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-900/20"
                  >
                    <p class="text-sm text-red-700 dark:text-red-300">
                      <strong>{m.api_keys_admin_revoked_label()}</strong>
                      {formatter.format(new Date(key.revoked_at))}
                      {#if key.revoked_reason_text}
                        <br /><span class="text-red-600 dark:text-red-400"
                          >{key.revoked_reason_text}</span
                        >
                      {/if}
                    </p>
                  </div>
                </div>
              {/if}
            </div>
          </div>
        {/if}
      </div>
    {/each}
  </div>
{/if}
