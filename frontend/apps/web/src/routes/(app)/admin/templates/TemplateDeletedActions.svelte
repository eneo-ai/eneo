<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@intric/intric-js";
  import { Button } from "@intric/ui";
  import { Undo, Trash2 } from "lucide-svelte";
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

<div class="flex items-center gap-2">
  <Button
    variant="positive-outlined"
    padding="icon-text"
    onclick={() => isRestoreOpen.set(true)}
    aria-label={m.restore()}
  >
    <Undo size={16} />
    {m.restore()}
  </Button>

  <Button
    variant="destructive"
    padding="icon-text"
    onclick={() => isPermanentDeleteOpen.set(true)}
    aria-label={m.permanent_delete()}
  >
    <Trash2 size={16} />
    {m.permanent_delete()}
  </Button>
</div>

<TemplateRestoreDialog openController={isRestoreOpen} {template} {type} />
<TemplatePermanentDeleteDialog openController={isPermanentDeleteOpen} {template} {type} />
