<script lang="ts">
  import SelectKnowledgeV2 from "$lib/features/knowledge/components/SelectKnowledgeV2.svelte";
  import AttachmentUploadTextButton from "$lib/features/attachments/components/AttachmentUploadTextButton.svelte";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { getIntric } from "$lib/core/Intric";
  import AttachmentItem from "$lib/features/attachments/components/AttachmentItem.svelte";
  import { getAppContext } from "$lib/core/AppContext";
  import { getAttachmentRules } from "$lib/features/attachments/getAttachmentRules";
  import { getTemplateController } from "../../TemplateController";
  import { fly } from "svelte/transition";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import WizardBackdrop from "./WizardBackdrop.svelte";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { selectedAttachments, selectedCollections, selectedTemplate }
  } = getTemplateController();

  const intric = getIntric();
  const { limits } = getAppContext();
  const rules = getAttachmentRules({ limits, resource: { completion_model: { vision: false } } });

  const {
    state: { attachments }
  } = initAttachmentManager({ intric, options: { rules } });

  attachments.subscribe((value) => selectedAttachments.set(value));
</script>

{#if $selectedTemplate}
  <div class="relative flex flex-col">
    <div class=" border-default flex w-full flex-col px-10 pt-12 pb-10">
      <div class="flex flex-col px-4">
        <span class="font-mono text-sm font-normal uppercase">{m.template_setup()}</span>
        <h3 class="flex items-center gap-3 pb-1 text-2xl font-extrabold">
          {formatEmojiTitle($selectedTemplate.name)}
        </h3>
        <p class="text-secondary max-w-[45ch]">
          {m.configure_template_settings()}
        </p>
      </div>

      <div class="border-dimmer mt-10 mb-6 border-t"></div>

      <div class="flex flex-col" in:fly|global={{ y: 5 }}>
        {#if $selectedTemplate.wizard.collections}
          <div class="flex flex-col p-4">
            <h4 class="flex items-center gap-4 text-lg font-medium">
              {$selectedTemplate.wizard.collections.title}
              {#if $selectedTemplate.wizard.collections.required}
                <span class="text-muted text-base font-normal">({m.required()})</span>{/if}
            </h4>
            <p class="text-secondary max-w-[65ch] pt-1 pb-2">
              {$selectedTemplate.wizard.collections.description}
            </p>

            <SelectKnowledgeV2 bind:selectedCollections={$selectedCollections} inDialog
            ></SelectKnowledgeV2>
          </div>
        {/if}

        {#if $selectedTemplate.wizard.attachments}
          <div class="flex flex-col p-4">
            <h4 class="flex items-center gap-4 text-lg font-medium">
              {$selectedTemplate.wizard.attachments.title}
              {#if $selectedTemplate.wizard.attachments.required}
                <span class="text-muted text-base font-normal">({m.required()})</span>{/if}
            </h4>
            <p class="text-secondary max-w-[65ch] pt-1">
              {$selectedTemplate.wizard.attachments.description}
            </p>
            <div class="flex flex-col gap-2 pt-4">
              {#each $attachments as attachment (attachment.id)}
                <AttachmentItem {attachment} borderOnLastItem></AttachmentItem>
              {/each}
              <AttachmentUploadTextButton></AttachmentUploadTextButton>
            </div>
          </div>
        {/if}
      </div>
    </div>

    <div class="absolute top-0 right-0 h-52 w-72 overflow-hidden">
      <WizardBackdrop></WizardBackdrop>
    </div>
  </div>
{:else}
  {m.no_template_selected()}
{/if}
