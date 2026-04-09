<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@intric/intric-js";
  import { Button } from "@intric/ui";
  import { RotateCcw } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { writable } from "svelte/store";
  import TemplateRollbackDialog from "$lib/features/templates/components/admin/TemplateRollbackDialog.svelte";

  type AssistantTemplate = components["schemas"]["AssistantTemplateAdminPublic"];
  type AppTemplate = components["schemas"]["AppTemplateAdminPublic"];
  type Template = AssistantTemplate | AppTemplate;

  let { template, type }: { template: Template; type: "assistant" | "app" } = $props();

  const rollbackOpenController = writable(false);
</script>

{#if template.original_snapshot}
  <Button onclick={() => rollbackOpenController.set(true)} aria-label={m.rollback()}>
    <RotateCcw size={16} />
    {m.rollback()}
  </Button>

  <TemplateRollbackDialog openController={rollbackOpenController} {template} {type} />
{/if}
