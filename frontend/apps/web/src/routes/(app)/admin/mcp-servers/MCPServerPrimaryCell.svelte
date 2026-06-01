<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Globe, Shield, ShieldCheck } from "lucide-svelte";

  type Props = {
    mcpServer: {
      name: string;
      description?: string | null;
      http_url: string;
      http_auth_type: string;
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
          classes: "bg-intric-100 text-intric-700 dark:bg-intric-900/50 dark:text-intric-300"
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
</div>
