<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { toastError } from "$lib/core/errors";
  import AssistantTemplateForm, {
    type AssistantTemplatePayload
  } from "$lib/features/templates/components/admin/AssistantTemplateForm.svelte";
  import { m } from "$lib/paraglide/messages";

  let { data } = $props();

  async function create(payload: AssistantTemplatePayload) {
    try {
      await data.eneo.templates.admin.createAssistant(payload);
      goto(resolve("/admin/templates?success=template_created"));
    } catch (error) {
      console.error("Failed to create template:", error);
      toastError(error, m.failed_to_create_template());
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.create_assistant_template()}</title>
</svelte:head>

<AssistantTemplateForm
  title={m.create_assistant_template()}
  submitLabel={m.create_template()}
  completionModels={data.completionModels}
  onSubmit={create}
/>
