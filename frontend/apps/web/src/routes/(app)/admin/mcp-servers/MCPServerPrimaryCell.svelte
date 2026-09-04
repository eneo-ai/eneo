<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Globe, KeyRound, Shield, ShieldCheck, Sparkles, UsersRound } from "lucide-svelte";
  import { getCapability } from "$lib/features/mcp/capabilities";

  type Props = {
    mcpServer: {
      name: string;
      description?: string | null;
      http_url: string;
      http_auth_type: string;
      provider_config?: { model?: string | null } | null;
      purpose?: string | null;
      audience?: string | null;
      user_groups?: Array<{ id: string; name: string }> | null;
      security_classification?: { name: string } | null;
    };
  };

  const { mcpServer }: Props = $props();

  // Nordic-inspired muted colors with better contrast for accessibility
  function getAuthConfig(type: string) {
    switch (type) {
      case "none":
        return {
          label: "Public",
          icon: Globe,
          classes: "bg-moss-100 text-moss-700 dark:bg-moss-900/50 dark:text-moss-300"
        };
      case "bearer":
        return {
          label: "Bearer",
          icon: Shield,
          classes: "bg-eneo-100 text-eneo-700 dark:bg-eneo-900/50 dark:text-eneo-300"
        };
      case "api_key_header":
        return {
          label: "API key",
          icon: KeyRound,
          classes: "bg-accent-dimmer text-accent-stronger"
        };
      case "internal":
        // Built-in provider: Eneo's own loopback server, no stored credentials.
        return {
          label: m.mcp_auth_internal(),
          icon: Sparkles,
          classes: "bg-accent-dimmer text-accent-stronger"
        };
      default:
        return {
          label: type,
          icon: Globe,
          classes: "bg-secondary text-secondary"
        };
    }
  }

  const authConfig = $derived(getAuthConfig(mcpServer.http_auth_type));
  const AuthIcon = $derived(authConfig.icon);
  // Capability providers carry their purpose as a chip so they stand out
  // from ordinary tool servers in the same list.
  const capability = $derived(getCapability(mcpServer.purpose));
  // Who a capability provider serves: the tenant default, or named groups.
  const audienceGroups = $derived(
    capability && mcpServer.audience === "groups" ? (mcpServer.user_groups ?? []) : []
  );
</script>

<div class="flex min-w-0 flex-col gap-1 py-0.5">
  <div class="flex items-center gap-2.5">
    <span class="text-default truncate leading-tight font-medium">{mcpServer.name}</span>
    <span
      class="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium {authConfig.classes}"
      role="status"
      aria-label={m.mcp_auth_type_aria({ label: authConfig.label })}
    >
      <AuthIcon class="h-3 w-3" aria-hidden="true" />
      {authConfig.label}
    </span>
    {#if capability}
      <span
        class="bg-accent-dimmer text-accent-stronger inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium"
        role="status"
        aria-label="{m.mcp_purpose_label()}: {capability.label()}"
      >
        <capability.icon class="h-3 w-3" aria-hidden="true" />
        {capability.label()}
      </span>
      <span
        class="bg-secondary text-secondary inline-flex min-w-0 shrink items-center gap-1 truncate rounded-md px-2 py-0.5 text-[11px] font-medium"
        role="status"
        aria-label="{m.mcp_audience_label()}: {audienceGroups.length > 0
          ? audienceGroups.map((group) => group.name).join(', ')
          : m.mcp_audience_everyone()}"
        title={audienceGroups.map((group) => group.name).join(", ")}
      >
        <UsersRound class="h-3 w-3 shrink-0" aria-hidden="true" />
        <span class="truncate">
          {#if audienceGroups.length > 0}
            {audienceGroups.map((group) => group.name).join(", ")}
          {:else}
            {m.mcp_audience_everyone()}
          {/if}
        </span>
      </span>
    {/if}
    {#if mcpServer.security_classification}
      <span
        class="bg-amethyst-100 text-amethyst-700 dark:bg-amethyst-900/50 dark:text-amethyst-300 inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium"
        role="status"
        aria-label="{m.security_classification()}: {mcpServer.security_classification.name}"
      >
        <ShieldCheck class="h-3 w-3" aria-hidden="true" />
        {mcpServer.security_classification.name}
      </span>
    {/if}
  </div>
  {#if mcpServer.description}
    <p class="text-muted line-clamp-1 text-sm leading-snug">{mcpServer.description}</p>
  {/if}
  {#if mcpServer.http_auth_type === "internal"}
    <!-- A built-in provider's endpoint is Eneo's own loopback: plumbing, not
         something the admin chose. The model is what they configured. -->
    <span class="text-dimmer inline-flex items-center gap-1.5 truncate text-xs">
      <span class="text-muted">{m.mcp_builtin_model()}:</span>
      <span class="font-mono">{mcpServer.provider_config?.model}</span>
    </span>
  {:else}
    <span
      class="text-dimmer inline-flex items-center gap-1.5 truncate font-mono text-xs"
      aria-label={m.mcp_server_url_aria()}
    >
      <span
        class="bg-positive-default inline-block h-1.5 w-1.5 animate-pulse rounded-full"
        aria-hidden="true"
      ></span>
      {mcpServer.http_url}
    </span>
  {/if}
</div>
