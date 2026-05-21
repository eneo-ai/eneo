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

  function isActive(prefix: string) {
    return currentPath.startsWith(prefix);
  }
</script>

<div class="flex h-full flex-col">
  <div class="border-default flex items-center gap-1 border-b px-6 pt-4">
    <Button
      variant={isActive("/admin/personal-chat/configuration") ? "default" : "ghost"}
      size="sm"
      onclick={() => goto(resolve("/admin/personal-chat/configuration"))}
    >
      Konfiguration
    </Button>
    <Button
      variant={isActive("/admin/personal-chat/prompts") ? "default" : "ghost"}
      size="sm"
      onclick={() => goto(resolve("/admin/personal-chat/prompts"))}
    >
      Promptbibliotek
    </Button>
  </div>
  <div class="flex-1 overflow-auto">
    {@render children?.()}
  </div>
</div>
