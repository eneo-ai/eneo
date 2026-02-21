<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Globe, Key, Shield, Settings2 } from "lucide-svelte";

  type Props = {
    mcpServer: {
      name: string;
      description?: string;
      http_url: string;
      http_auth_type: string;
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
      case "api_key":
        return {
          label: "API-nyckel",
          icon: Key,
          classes: "bg-ui-orange-100 text-ui-orange-700 dark:bg-ui-orange-900/50 dark:text-ui-orange-300"
        };
      case "custom_headers":
        return {
          label: "Anpassad",
          icon: Settings2,
          classes: "bg-amethyst-100 text-amethyst-700 dark:bg-amethyst-900/50 dark:text-amethyst-300"
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
</script>

<div class="flex flex-col gap-1 py-0.5 min-w-0">
  <div class="flex items-center gap-2.5">
    <span class="font-medium text-default truncate leading-tight">{mcpServer.name}</span>
    <span
      class="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium {authConfig.classes}"
      role="status"
      aria-label="Autentiseringstyp: {authConfig.label}"
    >
      <svelte:component this={authConfig.icon} class="h-3 w-3" aria-hidden="true" />
      {authConfig.label}
    </span>
  </div>
  {#if mcpServer.description}
    <p class="text-sm text-muted line-clamp-1 leading-snug">{mcpServer.description}</p>
  {/if}
  <span class="inline-flex items-center gap-1.5 text-xs text-dimmer truncate font-mono" aria-label="Server URL">
    <span class="inline-block h-1.5 w-1.5 rounded-full bg-positive-default animate-pulse" aria-hidden="true"></span>
    {mcpServer.http_url}
  </span>
</div>
