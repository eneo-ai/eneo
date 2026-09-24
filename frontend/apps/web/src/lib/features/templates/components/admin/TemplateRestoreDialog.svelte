<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { Undo } from "@lucide/svelte";
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

  async function restoreTemplate() {
    if (type === "assistant") {
      await eneo.templates.admin.restoreAssistant(template.id);
    } else {
      await eneo.templates.admin.restoreApp(template.id);
    }
    await invalidate("admin:templates:load");
  }
</script>

<ConfirmDialog
  bind:open
  title={m.restore_template()}
  description={m.restore_template_confirmation()}
  confirmLabel={m.restore()}
  pendingLabel={m.restoring()}
  variant="default"
  errorContext={m.failed_to_restore_template()}
  onConfirm={restoreTemplate}
>
  <div class="border-positive-default bg-positive-default/15 rounded-lg border px-4 py-3">
    <div class="flex items-start gap-3">
      <Undo class="text-positive-default shrink-0" size={20} aria-hidden="true" />
      <div class="flex flex-col gap-1">
        <div class="text-default font-semibold">{template.name}</div>
        <div class="text-muted text-sm">{m.template_will_be_restored()}</div>
      </div>
    </div>
  </div>
</ConfirmDialog>
