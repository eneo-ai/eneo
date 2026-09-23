<script lang="ts">
  import { getTemplateController } from "../TemplateController";
  import TemplateSmallPreviewGallery from "./gallery/TemplateSmallPreviewGallery.svelte";
  import CreateAppBackdrop from "./apps/CreateAppBackdrop.svelte";
  import CreateAssistantBackdrop from "./assistants/CreateAssistantBackdrop.svelte";
  import { m } from "$lib/paraglide/messages";

  let { kind }: { kind: "app" | "assistant" } = $props();

  const kinds = {
    app: {
      eyebrow: m.eneo_apps,
      description: m.apps_automation_description,
      action: m.create_new_app_arrow,
      Backdrop: CreateAppBackdrop
    },
    assistant: {
      eyebrow: m.eneo_assistants,
      description: m.assistants_intro_text,
      action: m.create_new_assistant_arrow,
      Backdrop: CreateAssistantBackdrop
    }
  };
  const config = $derived(kinds[kind]);

  const {
    state: { showCreateDialog }
  } = getTemplateController();
</script>

<div class="flex h-full flex-grow items-center justify-center">
  <div class="max-w-[640px]">
    <div
      class="border-default bg-primary relative mx-1 flex flex-col items-start overflow-clip rounded-2xl border px-10 py-8 text-left shadow-md"
    >
      <span class="font-mono text-sm uppercase">{config.eyebrow()}</span>
      <h3 class="mb-1 text-2xl font-extrabold">{m.lets_get_started()}</h3>
      <p class="text-secondary max-w-[50ch] pt-2 pr-48">
        {config.description()}
      </p>
      <button
        type="button"
        onclick={() => {
          $showCreateDialog = true;
        }}
        class="bg-accent-default text-on-fill hover:bg-accent-stronger mt-8 -ml-1 cursor-pointer rounded-lg px-3 py-1.5 text-center"
      >
        {config.action()}
      </button>

      <div class="absolute top-0 right-0 h-56 w-80 overflow-hidden">
        <config.Backdrop />
      </div>
    </div>
    <div class="h-2"></div>
    <TemplateSmallPreviewGallery></TemplateSmallPreviewGallery>
  </div>
</div>
