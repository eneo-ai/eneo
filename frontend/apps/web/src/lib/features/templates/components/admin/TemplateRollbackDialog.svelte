<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { RotateCcw } from "@lucide/svelte";
  import { invalidate } from "$app/navigation";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { getEneo } from "$lib/core/Eneo.js";
  import { m } from "$lib/paraglide/messages";

  type AssistantTemplate = components["schemas"]["AssistantTemplateAdminPublic"];
  type AppTemplate = components["schemas"]["AppTemplateAdminPublic"];
  type Template = AssistantTemplate | AppTemplate;

  let {
    open = $bindable(false),
    template,
    type
  }: {
    open?: boolean;
    template: Template;
    type: "assistant" | "app";
  } = $props();

  const eneo = getEneo();

  async function rollbackTemplate() {
    if (type === "assistant") {
      await eneo.templates.admin.rollbackAssistant(template.id);
    } else {
      await eneo.templates.admin.rollbackApp(template.id);
    }
    await invalidate("admin:templates:load");
  }
</script>

<ConfirmDialog
  bind:open
  title={m.rollback_template()}
  description={m.rollback_template_confirmation()}
  confirmLabel={m.rollback()}
  pendingLabel={m.restoring()}
  variant="default"
  errorContext={m.failed_to_rollback_template()}
  onConfirm={rollbackTemplate}
>
  <div class="border-accent-default bg-accent-default/10 rounded-lg border px-4 py-3">
    <div class="flex items-start gap-3">
      <RotateCcw class="text-accent-default mt-0.5 shrink-0" size={20} aria-hidden="true" />
      <div class="flex flex-col gap-2">
        <div class="text-default font-medium">{template.name}</div>
        <div class="text-muted text-sm">{m.rollback_template_description()}</div>
      </div>
    </div>
  </div>
</ConfirmDialog>
