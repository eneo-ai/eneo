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
    User,
    Eye,
    Pencil,
    ShieldCheck
  } from "lucide-svelte";
  import { slide, fly } from "svelte/transition";
  import AdminApiKeyActions from "./AdminApiKeyActions.svelte";

  let { keys = [], loading = false, onChanged, onSecret } = $props<{
    keys: ApiKeyV2[];
    loading: boolean;
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

  const formatter = new Intl.DateTimeFormat("sv-SE", {
    dateStyle: "medium",
    timeStyle: "short"
  });

  const relativeFormatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

  function formatRelativeDate(date: string | null | undefined): string {
    if (!date) return "Never";
    const d = new Date(date);
    const now = new Date();
    const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Yesterday";
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
  const scopeConfig: Record<string, { label: string; icon: typeof Building2; color: string }> = {
    tenant: { label: "Tenant", icon: Building2, color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300" },
    space: { label: "Space", icon: Building2, color: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300" },
    assistant: { label: "Assistant", icon: MessageSquare, color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300" },
    app: { label: "App", icon: AppWindow, color: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300" }
  };

  const stateConfig: Record<string, { label: string; color: Label.LabelColor; dotColor: string }> = {
    active: { label: "Active", color: "green", dotColor: "bg-green-500" },
    suspended: { label: "Suspended", color: "yellow", dotColor: "bg-yellow-500" },
    revoked: { label: "Revoked", color: "gray", dotColor: "bg-red-500" },
    expired: { label: "Expired", color: "gray", dotColor: "bg-gray-500" }
  };

  const permissionConfig: Record<string, { color: string; icon: typeof Eye }> = {
    read: { color: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300", icon: Eye },
    write: { color: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300", icon: Pencil },
    admin: { color: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300", icon: ShieldCheck }
  };

  function getKeyTypeConfig(keyType: string) {
    return keyType === "pk_"
      ? { label: "Public", icon: Globe, color: "text-orange-600 dark:text-orange-400", bgColor: "bg-orange-100 dark:bg-orange-900/30" }
      : { label: "Secret", icon: Lock, color: "text-blue-600 dark:text-blue-400", bgColor: "bg-blue-100 dark:bg-blue-900/30" };
  }
</script>

{#if loading}
  <!-- Skeleton loader -->
  <div class="space-y-3 animate-pulse">
    {#each Array(5) as _}
      <div class="rounded-xl border border-default bg-primary p-4">
        <div class="flex items-center gap-4">
          <div class="h-10 w-10 rounded-lg bg-subtle"></div>
          <div class="flex-1 space-y-2">
            <div class="h-4 w-40 rounded bg-subtle"></div>
            <div class="h-3 w-28 rounded bg-subtle"></div>
          </div>
          <div class="h-6 w-16 rounded bg-subtle"></div>
        </div>
      </div>
    {/each}
  </div>
{:else if keys.length === 0}
  <!-- Empty state -->
  <div class="rounded-xl border border-dashed border-default bg-subtle/50 p-12 text-center">
    <div class="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-accent-default/10">
      <Key class="h-8 w-8 text-accent-default" />
    </div>
    <h3 class="text-lg font-semibold text-default">No API Keys Found</h3>
    <p class="mt-2 text-sm text-muted max-w-md mx-auto">
      No API keys match your current filters. Try adjusting your search criteria.
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

      <div
        class="group rounded-xl border border-default bg-primary overflow-hidden transition-all duration-200
               hover:shadow-md hover:border-dimmer
               {isExpanded ? 'ring-2 ring-accent-default/20 border-accent-default/30' : ''}"
      >
        <!-- Main row -->
        <button
          type="button"
          onclick={() => toggleExpanded(key.id)}
          class="w-full px-5 py-4 text-left"
        >
          <div class="flex items-center gap-4">
            <!-- Key type icon -->
            <div class="flex h-11 w-11 items-center justify-center rounded-xl {keyTypeConf.bgColor}">
              <svelte:component this={keyTypeConf.icon} class="h-5 w-5 {keyTypeConf.color}" />
            </div>

            <!-- Key info -->
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-3 flex-wrap">
                <h4 class="font-semibold text-default truncate">{key.name}</h4>

                <!-- Status dot and badge -->
                <div class="flex items-center gap-1.5">
                  <span class="h-2 w-2 rounded-full {state.dotColor}"></span>
                  <span class="text-xs text-muted">{state.label}</span>
                </div>
              </div>

              <!-- Key preview -->
              <div class="mt-1 flex items-center gap-3 text-sm flex-wrap">
                <code class="font-mono text-muted">
                  {key.key_type}<span class="text-default/40">•••</span>{key.key_suffix}
                </code>

                <!-- Scope badge -->
                <span class="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium {scope.color}">
                  <svelte:component this={scope.icon} class="h-3 w-3" />
                  {scope.label}
                  {#if key.scope_id}
                    <span class="opacity-60">· {key.scope_id.slice(0, 8)}</span>
                  {/if}
                </span>

                <!-- Permission badge -->
                <span class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold uppercase {permission.color}">
                  <svelte:component this={permission.icon} class="h-3 w-3" />
                  {key.permission}
                </span>
              </div>
            </div>

            <!-- Right side info -->
            <div class="hidden lg:flex items-center gap-6 text-sm">
              <!-- Rate limit -->
              <div class="text-right">
                <p class="text-xs text-muted">Rate limit</p>
                <p class="font-medium text-default">
                  {key.rate_limit ? `${key.rate_limit}/hr` : "Default"}
                </p>
              </div>

              <!-- Expiration -->
              {#if daysUntil !== null}
                <div class="text-right">
                  <p class="text-xs text-muted">Expires</p>
                  <p class="font-medium {daysUntil <= 7 ? 'text-yellow-600 dark:text-yellow-400' : daysUntil <= 0 ? 'text-red-600 dark:text-red-400' : 'text-default'}">
                    {daysUntil <= 0 ? "Expired" : daysUntil === 1 ? "Tomorrow" : `${daysUntil} days`}
                  </p>
                </div>
              {/if}

              <!-- Last used -->
              <div class="text-right">
                <p class="text-xs text-muted">Last used</p>
                <p class="font-medium text-default">{formatRelativeDate(key.last_used_at)}</p>
              </div>
            </div>

            <!-- Actions and expand -->
            <div class="flex items-center gap-2">
              <AdminApiKeyActions apiKey={key} {onChanged} {onSecret} />

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
            class="border-t border-default bg-subtle/50 px-5 py-4"
            transition:slide={{ duration: 200 }}
          >
            <div class="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              <!-- Description -->
              {#if key.description}
                <div class="sm:col-span-2 lg:col-span-4">
                  <p class="text-sm text-muted">{key.description}</p>
                </div>
              {/if}

              <!-- Creator (admin-specific) -->
              {#if key.created_by_user_id}
                <div class="flex items-start gap-3">
                  <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
                    <User class="h-4 w-4 text-muted" />
                  </div>
                  <div>
                    <p class="text-xs text-muted">Created by</p>
                    <p class="text-sm font-mono text-default truncate max-w-[180px]" title={key.created_by_user_id}>
                      {key.created_by_user_id.slice(0, 8)}...
                    </p>
                  </div>
                </div>
              {/if}

              <!-- Created -->
              <div class="flex items-start gap-3">
                <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
                  <Calendar class="h-4 w-4 text-muted" />
                </div>
                <div>
                  <p class="text-xs text-muted">Created</p>
                  <p class="text-sm font-medium text-default">
                    {key.created_at ? formatter.format(new Date(key.created_at)) : "—"}
                  </p>
                </div>
              </div>

              <!-- Last used -->
              <div class="flex items-start gap-3">
                <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
                  <Activity class="h-4 w-4 text-muted" />
                </div>
                <div>
                  <p class="text-xs text-muted">Last Used</p>
                  <p class="text-sm font-medium text-default">
                    {key.last_used_at ? formatter.format(new Date(key.last_used_at)) : "Never"}
                  </p>
                </div>
              </div>

              <!-- Expires -->
              <div class="flex items-start gap-3">
                <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
                  <Clock class="h-4 w-4 text-muted" />
                </div>
                <div>
                  <p class="text-xs text-muted">Expires</p>
                  <p class="text-sm font-medium text-default">
                    {key.expires_at ? formatter.format(new Date(key.expires_at)) : "Never"}
                  </p>
                </div>
              </div>

              <!-- Rate limit -->
              <div class="flex items-start gap-3">
                <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-primary">
                  <Shield class="h-4 w-4 text-muted" />
                </div>
                <div>
                  <p class="text-xs text-muted">Rate Limit</p>
                  <p class="text-sm font-medium text-default">
                    {key.rate_limit ? `${key.rate_limit}/hr` : "Default"}
                  </p>
                </div>
              </div>

              <!-- Full Scope ID -->
              {#if key.scope_id}
                <div class="sm:col-span-2">
                  <p class="text-xs text-muted mb-2">Scope ID</p>
                  <code class="inline-block rounded-md bg-primary border border-default px-3 py-1.5 text-xs font-mono text-default">
                    {key.scope_id}
                  </code>
                </div>
              {/if}

              <!-- Allowed Origins (for pk_ keys) -->
              {#if key.key_type === "pk_" && key.allowed_origins?.length}
                <div class="sm:col-span-2">
                  <p class="text-xs text-muted mb-2">Allowed Origins</p>
                  <div class="flex flex-wrap gap-1.5">
                    {#each key.allowed_origins as origin}
                      <span class="inline-flex items-center gap-1.5 rounded-md bg-primary border border-default px-2.5 py-1 text-xs font-mono text-default">
                        <Globe class="h-3 w-3 text-muted" />
                        {origin}
                      </span>
                    {/each}
                  </div>
                </div>
              {/if}

              <!-- Allowed IPs (for sk_ keys) -->
              {#if key.key_type === "sk_" && key.allowed_ips?.length}
                <div class="sm:col-span-2">
                  <p class="text-xs text-muted mb-2">Allowed IPs</p>
                  <div class="flex flex-wrap gap-1.5">
                    {#each key.allowed_ips as ip}
                      <span class="inline-flex items-center gap-1.5 rounded-md bg-primary border border-default px-2.5 py-1 text-xs font-mono text-default">
                        <Server class="h-3 w-3 text-muted" />
                        {ip}
                      </span>
                    {/each}
                  </div>
                </div>
              {/if}

              <!-- Suspension info -->
              {#if key.state === "suspended" && key.suspended_at}
                <div class="sm:col-span-2 lg:col-span-4">
                  <div class="rounded-lg border border-yellow-200 bg-yellow-50 dark:border-yellow-800 dark:bg-yellow-900/20 p-3">
                    <p class="text-sm text-yellow-700 dark:text-yellow-300">
                      <strong>Suspended:</strong> {formatter.format(new Date(key.suspended_at))}
                      {#if key.suspended_reason_text}
                        <br /><span class="text-yellow-600 dark:text-yellow-400">{key.suspended_reason_text}</span>
                      {/if}
                    </p>
                  </div>
                </div>
              {/if}

              <!-- Revocation info -->
              {#if key.state === "revoked" && key.revoked_at}
                <div class="sm:col-span-2 lg:col-span-4">
                  <div class="rounded-lg border border-red-200 bg-red-50 dark:border-red-800 dark:bg-red-900/20 p-3">
                    <p class="text-sm text-red-700 dark:text-red-300">
                      <strong>Revoked:</strong> {formatter.format(new Date(key.revoked_at))}
                      {#if key.revoked_reason_text}
                        <br /><span class="text-red-600 dark:text-red-400">{key.revoked_reason_text}</span>
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
