<script lang="ts">
  import TemplateGallery from "./gallery/TemplateGallery.svelte";
  import { getTemplateController } from "../TemplateController";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import TemplateIcon from "./TemplateIcon.svelte";
  import { Input } from "@intric/ui";
  import { IconChevronUpDown } from "@intric/icons/chevron-up-down";
  import { IconInfo } from "@intric/icons/info";
  import { IconCopy } from "@intric/icons/copy";
  import { IconFile } from "@intric/icons/file";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { name, creationMode, selectedTemplate, showTemplateGallery, hasWizard },
    resourceName
  } = getTemplateController();

  const { featureFlags } = getAppContext();
</script>

<div class="outer relative flex flex-grow flex-col items-start justify-start text-left">
  <div class=" border-default flex w-full flex-col px-10 pt-12 pb-10">
    <h3 class="px-4 pb-1 text-2xl font-extrabold">{m.create_a_new_resource({ resourceName: resourceName.singular })}</h3>
    <p class="text-secondary max-w-[60ch] pr-36 pl-4">
      {#if featureFlags.showTemplates}
        {m.create_from_scratch_or_template({ resourceName: resourceName.singular })}
      {:else}
        {m.get_started_creating_new_assistant()}
      {/if}
    </p>
    <!-- <div class="h-8"></div> -->
    <div class="border-dimmer mt-14 mb-2 border-t"></div>
    <div class="flex flex-col gap-1 pt-6 pb-4">
      <span class="px-4 pb-1 text-lg font-medium">{m.assistant_name()}</span>
      <Input.Text bind:value={$name} hiddenLabel inputClass="!text-lg !py-6 !px-4" required
        >{m.assistant_name()}</Input.Text
      >
    </div>
    {#if featureFlags.showTemplates}
      <div class="grid grid-cols-2 gap-4">
        <button
          data-selected={$creationMode === "blank"}
          on:click|preventDefault={() => ($creationMode = "blank")}
          class="selector"
        >
          <div class="flex w-full items-center justify-start gap-2 text-left">
            <IconFile></IconFile>
            <span class="text-dynamic-stronger line-clamp-2">
              {m.create_blank_assistant()}</span
            >
          </div>
        </button>
        <div class="relative flex">
          <button
            data-selected={$creationMode === "template"}
            on:click|preventDefault={() => {
              if ($creationMode === "template" || $selectedTemplate === null) {
                $showTemplateGallery = true;
              }
              $creationMode = "template";
            }}
            class="selector"
          >
            <div class="flex w-full items-center justify-start gap-2 pr-6 text-left">
              {#if $selectedTemplate}
                <TemplateIcon template={$selectedTemplate}></TemplateIcon>
                <span class="text-dynamic-stronger truncate"
                  >{formatEmojiTitle($selectedTemplate.name)}</span
                >
              {:else}
                <IconCopy></IconCopy>
                {m.start_with_template()}
              {/if}
              <div class="flex-grow"></div>
            </div>
          </button>
          <button
            class="border-default text-secondary hover:bg-hover-default absolute top-[50%] right-2 -translate-y-[50%] rounded border p-1"
            on:click|preventDefault={() => {
              $showTemplateGallery = true;
            }}
          >
            <IconChevronUpDown></IconChevronUpDown>
          </button>
        </div>
      </div>

      {#if $hasWizard}
        <p class="text-secondary translate-y-5 p-2 text-center">
          <IconInfo class="inline"></IconInfo>
          {m.template_offers_additional_options()}
        </p>
      {/if}

      <TemplateGallery></TemplateGallery>
    {/if}
  </div>
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  button.selector {
    @apply border-default text-muted flex h-[3.25rem] flex-grow items-center justify-between overflow-hidden rounded-lg border p-3 pr-2 shadow;
  }

  button:hover.selector {
    @apply border-stronger bg-hover-default text-primary ring-default cursor-pointer ring-2;
  }

  button[data-selected="true"].selector {
    @apply border-accent-default bg-accent-dimmer text-accent-stronger shadow-accent-dimmer ring-accent-default shadow-lg ring-1 focus:outline-offset-4;
  }
</style>
