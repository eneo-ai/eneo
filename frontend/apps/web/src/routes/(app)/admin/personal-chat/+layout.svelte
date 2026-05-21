<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Button } from "$lib/components/ui/button/index.js";

  let { children } = $props();

  const currentPath = $derived($page.url.pathname);
  const configurationPath = $derived(resolve("/admin/personal-chat/configuration"));
  const promptsPath = $derived(resolve("/admin/personal-chat/prompts"));

  function isActive(prefix: string) {
    return currentPath.startsWith(prefix);
  }
</script>

<div class="flex h-full min-w-0 flex-grow flex-col overflow-hidden">
  <div class="border-default flex items-center gap-1 border-b px-6 pt-4">
    <Button
      variant={isActive(configurationPath) ? "default" : "ghost"}
      size="sm"
      onclick={() => goto(resolve("/admin/personal-chat/configuration"))}
    >
      Konfiguration
    </Button>
    <Button
      variant={isActive(promptsPath) ? "default" : "ghost"}
      size="sm"
      onclick={() => goto(resolve("/admin/personal-chat/prompts"))}
    >
      Promptbibliotek
    </Button>
  </div>
  <div class="min-h-0 flex-1 overflow-auto">
    {@render children?.()}
  </div>
</div>
