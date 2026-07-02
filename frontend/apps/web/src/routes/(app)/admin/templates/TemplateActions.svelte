<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { Button, Dropdown } from "@eneo/ui";
  import {
    MoreVertical,
    Edit,
    Trash2,
    RotateCcw,
    ArrowUpToLine,
    ArrowDownToLine
  } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { writable } from "svelte/store";
  import { goto, invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { getEneo } from "$lib/core/Eneo";
  import TemplateDeleteDialog from "$lib/features/templates/components/admin/TemplateDeleteDialog.svelte";
  import TemplateRollbackDialog from "$lib/features/templates/components/admin/TemplateRollbackDialog.svelte";

  type AssistantTemplate = components["schemas"]["AssistantTemplateAdminPublic"];
  type AppTemplate = components["schemas"]["AppTemplateAdminPublic"];
  type Template = AssistantTemplate | AppTemplate;

  let { template, type }: { template: Template; type: "assistant" | "app" } = $props();

  const eneo = getEneo();
  let isDeleteOpen = writable(false);
  let isRollbackOpen = writable(false);

  function handleEdit() {
    goto(resolve(`/admin/templates/edit/${type}/${template.id}`));
  }

  async function toggleDefault() {
    try {
      const newDefaultValue = !template.is_default;

      if (type === "assistant") {
        await eneo.templates.admin.toggleDefaultAssistant(template.id, newDefaultValue);
      } else {
        await eneo.templates.admin.toggleDefaultApp(template.id, newDefaultValue);
      }

      template.is_default = newDefaultValue;
      await invalidate("/admin/templates");
    } catch (e) {
      console.error("Error toggling default status:", e);
      toastError(e, m.error_changing_default_status());
    }
  }
</script>

<Dropdown.Root>
  <Dropdown.Trigger asFragment let:trigger>
    <Button is={trigger} padding="icon" aria-label={m.actions()}>
      <MoreVertical size={16} />
    </Button>
  </Dropdown.Trigger>

  <Dropdown.Menu let:item>
    <Button is={item} padding="icon-leading" onclick={handleEdit}>
      <Edit size={16} />
      {m.edit()}
    </Button>

    <Button is={item} padding="icon-leading" onclick={toggleDefault}>
      {#if template.is_default}
        <ArrowDownToLine size={16} />
        {m.unset_default_status()}
      {:else}
        <ArrowUpToLine size={16} />
        {m.set_as_default_template()}
      {/if}
    </Button>

    {#if template.original_snapshot}
      <Button is={item} padding="icon-leading" onclick={() => isRollbackOpen.set(true)}>
        <RotateCcw size={16} />
        {m.rollback()}
      </Button>
    {/if}

    <Button
      is={item}
      padding="icon-leading"
      onclick={() => isDeleteOpen.set(true)}
      variant="destructive"
    >
      <Trash2 size={16} />
      {m.delete()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

<TemplateDeleteDialog openController={isDeleteOpen} {template} {type} />
{#if template.original_snapshot}
  <TemplateRollbackDialog openController={isRollbackOpen} {template} {type} />
{/if}
