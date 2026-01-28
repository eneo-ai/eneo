<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  type Props = {
    mcpServer: {
      name: string;
      description?: string;
      http_url: string;
      http_auth_type: string;
    };
  };

  const { mcpServer }: Props = $props();

  function getAuthTypeColor(type: string) {
    switch (type) {
      case "none":
        return "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200";
      case "bearer":
        return "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200";
      case "api_key":
        return "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200";
      case "custom_headers":
        return "bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200";
      default:
        return "bg-gray-100 text-gray-800 dark:bg-gray-900 dark:text-gray-200";
    }
  }

  function formatAuthType(type: string) {
    if (type === "none") return "Public";
    if (type === "bearer") return "Bearer";
    if (type === "api_key") return "API Key";
    if (type === "custom_headers") return "Custom";
    return type;
  }
</script>

<div class="flex flex-col gap-0.5 py-1 min-w-0">
  <div class="flex items-center gap-2 flex-wrap">
    <span class="font-medium text-default truncate">{mcpServer.name}</span>
    <span
      class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium shrink-0 {getAuthTypeColor(
        mcpServer.http_auth_type
      )}"
    >
      {formatAuthType(mcpServer.http_auth_type)}
    </span>
  </div>
  {#if mcpServer.description}
    <span class="text-sm text-muted line-clamp-1">{mcpServer.description}</span>
  {/if}
  <span class="text-xs text-dimmer truncate">{mcpServer.http_url}</span>
</div>
