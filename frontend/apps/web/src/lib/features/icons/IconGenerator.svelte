<script lang="ts">
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { Button, Dialog } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { writable } from "svelte/store";
  import * as m from "$lib/paraglide/messages";
  import type { createIntric } from "@intric/intric-js";

  type Intric = ReturnType<typeof createIntric>;

  export let intric: Intric;
  export let resourceName: string;
  export let resourceDescription: string | null = null;
  export let systemPrompt: string | null = null;

  const dispatch = createEventDispatcher<{
    select: File;
  }>();

  let showDialog = writable(false);
  let prompt = "";
  let isGenerating = false;
  let isLoadingPrompt = false;
  let error: string | null = null;

  interface ImageVariant {
    index: number;
    blob_base64: string;
    mimetype: string;
    revised_prompt?: string;
  }

  let variants: ImageVariant[] = [];
  let selectedVariantIndex: number | null = null;

  async function loadPromptPreview() {
    isLoadingPrompt = true;
    error = null;
    try {
      const response = await intric.imageModels.previewPrompt({
        resource_name: resourceName,
        resource_description: resourceDescription ?? undefined,
        system_prompt: systemPrompt ?? undefined
      });
      prompt = response.prompt;
    } catch (e) {
      console.error("Failed to load prompt preview:", e);
      // Use a basic fallback prompt
      prompt = `Professional minimalist icon for "${resourceName}". Simple geometric shapes, clean design, modern aesthetic.`;
    } finally {
      isLoadingPrompt = false;
    }
  }

  async function openDialog() {
    $showDialog = true;
    variants = [];
    selectedVariantIndex = null;
    error = null;
    await loadPromptPreview();
  }

  async function generateVariants() {
    isGenerating = true;
    error = null;
    variants = [];
    selectedVariantIndex = null;

    try {
      const response = await intric.imageModels.generateIconVariants({
        resource_name: resourceName,
        resource_description: resourceDescription ?? undefined,
        system_prompt: systemPrompt ?? undefined,
        custom_prompt: prompt,
        num_variants: 4
      });
      variants = response.variants;
      if (response.generated_prompt && response.generated_prompt !== prompt) {
        // Update the prompt if a different one was generated
        prompt = response.generated_prompt;
      }
    } catch (e: any) {
      console.error("Failed to generate icons:", e);
      error = e?.message || m.icon_generate_failed?.() || "Failed to generate icons. Please try again.";
    } finally {
      isGenerating = false;
    }
  }

  function selectVariant(index: number) {
    selectedVariantIndex = index;
  }

  async function confirmSelection() {
    if (selectedVariantIndex === null) return;

    const variant = variants[selectedVariantIndex];
    if (!variant) return;

    // Convert base64 to blob and then to File
    const byteCharacters = atob(variant.blob_base64);
    const byteNumbers = new Array(byteCharacters.length);
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i);
    }
    const byteArray = new Uint8Array(byteNumbers);
    const blob = new Blob([byteArray], { type: variant.mimetype });

    // Determine file extension
    const ext = variant.mimetype.split("/")[1] || "png";
    const file = new File([blob], `generated-icon.${ext}`, { type: variant.mimetype });

    dispatch("select", file);
    $showDialog = false;
  }

  function getVariantSrc(variant: ImageVariant): string {
    return `data:${variant.mimetype};base64,${variant.blob_base64}`;
  }
</script>

<button
  on:click={openDialog}
  class="border-default hover:bg-hover-stronger flex h-12 w-full cursor-pointer items-center justify-center gap-2 rounded-lg border transition-colors"
>
  <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
    <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
  </svg>
  <span>{m.icon_generate?.() || "Generate with AI"}</span>
</button>

<Dialog.Root openController={showDialog}>
  <Dialog.Content width="medium">
    <Dialog.Title>{m.icon_generate_title?.() || "Generate Icon with AI"}</Dialog.Title>

    <Dialog.Section>
      <div class="flex flex-col gap-4">
        <div class="flex flex-col gap-2">
          <label for="iconPrompt" class="text-sm font-medium">
            {m.icon_prompt_label?.() || "Icon Description"}
          </label>
          {#if isLoadingPrompt}
            <div class="border-default bg-primary flex h-24 items-center justify-center rounded-lg border">
              <IconLoadingSpinner class="animate-spin" />
            </div>
          {:else}
            <textarea
              id="iconPrompt"
              bind:value={prompt}
              rows={3}
              class="border-default bg-primary ring-default rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              placeholder={m.icon_prompt_placeholder?.() || "Describe the icon you want to generate..."}
            ></textarea>
          {/if}
        </div>

        <Button
          variant="primary"
          on:click={generateVariants}
          disabled={isGenerating || isLoadingPrompt || !prompt.trim()}
          class="w-full"
        >
          {#if isGenerating}
            <IconLoadingSpinner class="mr-2 animate-spin" />
            {m.icon_generating?.() || "Generating..."}
          {:else if variants.length > 0}
            {m.icon_regenerate?.() || "Regenerate"}
          {:else}
            {m.icon_generate_button?.() || "Generate Icons"}
          {/if}
        </Button>

        {#if error}
          <div class="bg-destructive/10 text-destructive rounded-lg px-4 py-2 text-sm">
            {error}
          </div>
        {/if}

        {#if variants.length > 0}
          <div class="flex flex-col gap-2">
            <p class="text-sm font-medium">{m.icon_select_variant?.() || "Select a variant:"}</p>
            <div class="grid grid-cols-2 gap-3">
              {#each variants as variant (variant.index)}
                <button
                  class="border-default hover:border-primary relative aspect-square overflow-hidden rounded-lg border-2 transition-all {selectedVariantIndex === variant.index ? 'border-primary ring-primary ring-2' : ''}"
                  on:click={() => selectVariant(variant.index)}
                >
                  <img
                    src={getVariantSrc(variant)}
                    alt="Generated icon variant {variant.index + 1}"
                    class="h-full w-full object-cover"
                  />
                  {#if selectedVariantIndex === variant.index}
                    <div class="bg-primary absolute bottom-1 right-1 rounded-full p-1">
                      <svg class="text-on-primary h-4 w-4" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                      </svg>
                    </div>
                  {/if}
                </button>
              {/each}
            </div>
          </div>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close} variant="secondary">{m.cancel?.() || "Cancel"}</Button>
      <Button
        variant="positive"
        on:click={confirmSelection}
        disabled={selectedVariantIndex === null}
      >
        {m.icon_use_selected?.() || "Use Selected Icon"}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
