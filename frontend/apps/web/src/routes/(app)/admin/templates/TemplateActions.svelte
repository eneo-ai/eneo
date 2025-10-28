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

  <Dropdown.Menu let:item>
    <Button is={item} padding="icon-leading" on:click={handleEdit}>
      <Edit size={16} />
      {m.edit()}
    </Button>

    {#if template.original_snapshot}
      <Button is={item} padding="icon-leading" on:click={() => isRollbackOpen.set(true)}>
        <RotateCcw size={16} />
        {m.rollback()}
      </Button>
    {/if}

    <Button is={item} padding="icon-leading" on:click={() => isDeleteOpen.set(true)} variant="destructive">
      <Trash2 size={16} />
      {m.delete()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

<TemplateDeleteDialog openController={isDeleteOpen} {template} {type} />
{#if template.original_snapshot}
  <TemplateRollbackDialog openController={isRollbackOpen} {template} {type} />
{/if}
