<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@intric/intric-js";
  import { Button, Dropdown } from "@intric/ui";
  import { MoreVertical, Undo, Trash2 } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { writable } from "svelte/store";
  import TemplateRestoreDialog from "$lib/features/templates/components/admin/TemplateRestoreDialog.svelte";
  import TemplatePermanentDeleteDialog from "$lib/features/templates/components/admin/TemplatePermanentDeleteDialog.svelte";

  type AssistantTemplate = components["schemas"]["AssistantTemplateAdminPublic"];
  type AppTemplate = components["schemas"]["AppTemplateAdminPublic"];
  type Template = AssistantTemplate | AppTemplate;

  let { template, type }: { template: Template; type: "assistant" | "app" } = $props();

  let isRestoreOpen = writable(false);
  let isPermanentDeleteOpen = writable(false);
</script>

<Dropdown.Root>
  <Dropdown.Trigger asFragment let:trigger>
    <Button
      is={trigger}
      padding="icon"
      aria-label={m.actions()}
    >
      <MoreVertical size={16} />
    </Button>
  </Dropdown.Trigger>

  <Dropdown.Menu let:item>
    <Button
      is={item}
      padding="icon-leading"
      onclick={() => isRestoreOpen.set(true)}
    >
      <Undo size={16} />
      {m.restore()}
    </Button>

    <Button
      is={item}
      padding="icon-leading"
      variant="destructive"
      onclick={() => isPermanentDeleteOpen.set(true)}
    >
      <Trash2 size={16} />
      {m.permanent_delete()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

<TemplateRestoreDialog openController={isRestoreOpen} {template} {type} />
<TemplatePermanentDeleteDialog openController={isPermanentDeleteOpen} {template} {type} />
