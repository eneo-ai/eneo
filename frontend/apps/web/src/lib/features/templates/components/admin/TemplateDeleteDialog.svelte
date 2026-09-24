<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { AlertTriangle } from "@lucide/svelte";
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

  async function deleteTemplate() {
    if (type === "assistant") {
      await eneo.templates.admin.deleteAssistant(template.id);
    } else {
      await eneo.templates.admin.deleteApp(template.id);
    }
    await invalidate("admin:templates:load");
  }
</script>

<ConfirmDialog
  bind:open
  title={m.delete_template()}
  description={m.delete_template_confirmation()}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.failed_to_delete_template()}
  onConfirm={deleteTemplate}
>
  <div class="border-warning-default bg-warning-default/15 rounded-lg border px-4 py-3">
    <div class="flex items-start gap-3">
      <AlertTriangle class="text-warning-default shrink-0" size={20} aria-hidden="true" />
      <div class="flex flex-col gap-1">
        <div class="text-default font-semibold">{template.name}</div>
        <div class="text-dimmer text-sm">{m.permanent_action()}</div>
      </div>
    </div>
  </div>
</ConfirmDialog>
