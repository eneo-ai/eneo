<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Plus } from "lucide-svelte";
  import { invalidate } from "$app/navigation";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { Intric } from "@intric/intric-js";

  type Template = Awaited<ReturnType<Intric["helpAssistants"]["admin"]["listTemplates"]>>[number];

  let { templates, intric }: { templates: Template[]; intric: Intric } = $props();

  const install = createAsyncState(async (kind: Template["kind"]) => {
    try {
      // Installs a blank helper (enabled, not visible). The admin then pastes
      // instructions on the helper's settings page before enabling visibility.
      await intric.helpAssistants.admin.install({ kind });
      await invalidate("admin:help-assistants:load");
    } catch (e) {
      toastError(e);
    }
  });

  const noneAvailable = $derived(templates.length === 0);
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button
        {...props}
        disabled={noneAvailable || install.isLoading}
        title={noneAvailable ? m.admin_help_assistants_add_none_available() : undefined}
      >
        <Plus class="size-4" />
        {m.admin_help_assistants_add_button()}
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <!-- Fixed, viewport-capped width so the box doesn't grow to the widest
       description (the menu-item base is `w-max` + `whitespace-nowrap`); items
       stack and wrap instead. -->
  <DropdownMenu.Content align="end" class="w-80 max-w-[calc(100vw-2rem)]">
    <DropdownMenu.Label>{m.admin_help_assistants_add_menu_label()}</DropdownMenu.Label>
    <DropdownMenu.Separator />
    {#each templates as template (template.kind)}
      <DropdownMenu.Item
        onclick={() => install(template.kind)}
        class="cursor-pointer flex-col items-start gap-0.5 whitespace-normal"
      >
        <span class="font-medium">{template.name}</span>
        <span class="text-muted-foreground text-xs leading-snug">{template.description}</span>
      </DropdownMenu.Item>
    {/each}
  </DropdownMenu.Content>
</DropdownMenu.Root>
