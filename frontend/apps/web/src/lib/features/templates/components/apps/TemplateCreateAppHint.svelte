<script lang="ts">
  import { Button } from "@intric/ui";
  import CreateAppBackdrop from "./CreateAppBackdrop.svelte";
  import { getTemplateController } from "../../TemplateController";
  import TemplateSmallPreviewGallery from "../gallery/TemplateSmallPreviewGallery.svelte";

  const {
    state: { showCreateDialog }
  } = getTemplateController();
  import { m } from "$lib/paraglide/messages";
</script>

<div class="flex h-full flex-grow items-center justify-center">
  <div class="max-w-[640px]">
    <div
      class="border-default bg-primary relative mx-1 flex flex-col items-start overflow-clip rounded-2xl border px-10 py-8 text-left shadow-md"
    >
      <span class="font-mono text-sm uppercase">{m.eneo_apps()}</span>
      <h3 class="b-1 text-2xl font-extrabold">{m.lets_get_started()}</h3>
      <p class="text-secondary max-w-[50ch] pt-2 pr-48">
        {m.apps_automation_description()}
      </p>
      <Button
        unstyled
        on:click={() => {
          $showCreateDialog = true;
        }}
        class="bg-accent-default text-on-fill hover:bg-accent-stronger mt-8 -ml-1 rounded-lg px-3 py-1.5 text-center"
      >
        {m.create_new_app_arrow()}
      </Button>

      <div class="absolute top-0 right-0 h-56 w-80 overflow-hidden">
        <CreateAppBackdrop></CreateAppBackdrop>
      </div>
    </div>
    <div class="h-2"></div>
    <TemplateSmallPreviewGallery></TemplateSmallPreviewGallery>
  </div>
</div>
