<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@intric/intric-js";
  import { Button, Dropdown } from "@intric/ui";
  import { MoreVertical, Edit, Trash2, RotateCcw, ArrowUpToLine, ArrowDownToLine } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { writable } from "svelte/store";
  import { goto, invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import TemplateDeleteDialog from "$lib/features/templates/components/admin/TemplateDeleteDialog.svelte";
  import TemplateRollbackDialog from "$lib/features/templates/components/admin/TemplateRollbackDialog.svelte";

  type AssistantTemplate = components["schemas"]["AssistantTemplateAdminPublic"];
  type AppTemplate = components["schemas"]["AppTemplateAdminPublic"];
  type Template = AssistantTemplate | AppTemplate;

  let { template, type }: { template: Template; type: "assistant" | "app" } = $props();

  const intric = getIntric();
  let isDeleteOpen = writable(false);
  let isRollbackOpen = writable(false);

  function handleEdit() {
    goto(`/admin/templates/edit/${type}/${template.id}`);
  }

  async function toggleDefault() {
    try {
      const newDefaultValue = !template.is_default;

      if (type === "assistant") {
        await intric.templates.admin.toggleDefaultAssistant(template.id, newDefaultValue);
      } else {
        await intric.templates.admin.toggleDefaultApp(template.id, newDefaultValue);
      }

      template.is_default = newDefaultValue;
      await invalidate("/admin/templates");
    } catch (e) {
      console.error("Error toggling default status:", e);
      alert(m.error_changing_default_status?.() || "Error changing default status");
    }
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

    <Button is={item} padding="icon-leading" onclick={() => isDeleteOpen.set(true)} variant="destructive">
      <Trash2 size={16} />
      {m.delete()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

<TemplateDeleteDialog openController={isDeleteOpen} {template} {type} />
{#if template.original_snapshot}
  <TemplateRollbackDialog openController={isRollbackOpen} {template} {type} />
{/if}
