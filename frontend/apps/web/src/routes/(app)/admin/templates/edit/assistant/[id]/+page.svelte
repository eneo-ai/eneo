<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { toastError } from "$lib/core/errors";
  import AssistantTemplateForm, {
    type AssistantTemplatePayload
  } from "$lib/features/templates/components/admin/AssistantTemplateForm.svelte";
  import { m } from "$lib/paraglide/messages";

  let { data } = $props();

  async function update(payload: AssistantTemplatePayload) {
    try {
      await data.eneo.templates.admin.updateAssistant(data.template.id, payload);
      goto(resolve("/admin/templates?success=template_updated"));
    } catch (error) {
      console.error("Failed to update template:", error);
      toastError(error);
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.edit_assistant_template()}</title>
</svelte:head>

<AssistantTemplateForm
  initial={data.template}
  title={m.edit_assistant_template()}
  submitLabel={m.save_changes()}
  completionModels={data.completionModels}
  onSubmit={update}
/>
