<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@intric/intric-js";
  import { Button, Dropdown } from "@intric/ui";
  import { MoreVertical, Edit, Trash2, RotateCcw } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { writable } from "svelte/store";
  import { goto } from "$app/navigation";
  import TemplateDeleteDialog from "$lib/features/templates/components/admin/TemplateDeleteDialog.svelte";
  import TemplateRollbackDialog from "$lib/features/templates/components/admin/TemplateRollbackDialog.svelte";

  type AssistantTemplate = components["schemas"]["AssistantTemplateAdminPublic"];
  type AppTemplate = components["schemas"]["AppTemplateAdminPublic"];
  type Template = AssistantTemplate | AppTemplate;

  let { template, type }: { template: Template; type: "assistant" | "app" } = $props();

  let isDeleteOpen = writable(false);
  let isRollbackOpen = writable(false);

  function handleEdit() {
    goto(`/admin/templates/edit/${type}/${template.id}`);
  }
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

  <Dropdown.Content align="end">
    <Dropdown.Item onclick={handleEdit}>
      <Edit size={16} />
      {m.edit()}
    </Dropdown.Item>

    {#if template.original_snapshot}
      <Dropdown.Item onclick={() => isRollbackOpen.set(true)}>
        <RotateCcw size={16} />
        {m.rollback()}
      </Dropdown.Item>
    {/if}

    <Dropdown.Separator />

    <Dropdown.Item onclick={() => isDeleteOpen.set(true)} class="text-negative-default">
      <Trash2 size={16} />
      {m.delete()}
    </Dropdown.Item>
  </Dropdown.Content>
</Dropdown.Root>

<TemplateDeleteDialog openController={isDeleteOpen} {template} {type} />
{#if template.original_snapshot}
  <TemplateRollbackDialog openController={isRollbackOpen} {template} {type} />
{/if}
