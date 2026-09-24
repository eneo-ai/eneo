<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { toastError } from "$lib/core/errors";
  import AppTemplateForm, {
    type AppTemplatePayload
  } from "$lib/features/templates/components/admin/AppTemplateForm.svelte";
  import { m } from "$lib/paraglide/messages";

  let { data } = $props();

  async function create(payload: AppTemplatePayload) {
    try {
      await data.eneo.templates.admin.createApp(payload);
      goto(resolve("/admin/templates?success=template_created"));
    } catch (error) {
      console.error("Failed to create template:", error);
      toastError(error, m.failed_to_create_template());
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.create_app_template()}</title>
</svelte:head>

<AppTemplateForm
  title={m.create_app_template()}
  submitLabel={m.create_template()}
  completionModels={data.completionModels}
  onSubmit={create}
/>
