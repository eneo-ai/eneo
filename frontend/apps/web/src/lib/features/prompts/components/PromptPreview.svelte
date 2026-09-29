<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getPromptManager } from "../PromptManager";
  import MemberChip from "../../spaces/components/MemberChip.svelte";
  import EditPromptDescription from "./EditPromptDescription.svelte";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { previewedPrompt, showPromptVersionDialog },
    onPromptSelected
  } = getPromptManager();
</script>

<div class="flex flex-col gap-3.5">
  {#if $previewedPrompt}
    <section class="flex-grow">
      <div
        class="border-default bg-primary sticky top-0 flex items-center justify-between border-b px-4 py-2.5 font-medium backdrop-blur"
      >
        <h2 class="font-medium">
          <span class="sr-only">{m.previewing_prompt_created_at()}</span>
          <span aria-hidden="true">{m.version()}:</span>
          {formatDateTime($previewedPrompt?.created_at)}
        </h2>
        <MemberChip member={$previewedPrompt.user}></MemberChip>
      </div>

      <div class="flex-grow overflow-y-auto p-8 whitespace-pre-wrap">
        {$previewedPrompt.text}
      </div>
    </section>

    <div class="flex flex-col gap-3">
      {#if $previewedPrompt.description}
        <div
          class="border-accent-stronger bg-accent-dimmer text-accent-stronger rounded-md border px-5 py-4"
        >
          {$previewedPrompt.description}
        </div>
      {/if}

      <div class=" flex items-end justify-between">
        {#key $previewedPrompt.id}
          <EditPromptDescription prompt={$previewedPrompt}></EditPromptDescription>
        {/key}

        <Button
          disabled={$previewedPrompt.is_selected ?? false}
          onclick={() => {
            $showPromptVersionDialog = false;
            onPromptSelected($previewedPrompt);
          }}
          >{m.restore_this_version()}
        </Button>
      </div>
    </div>
  {:else}
    <div class="text-secondary flex h-full w-full items-center justify-center">
      {m.please_select_prompt()}
    </div>
  {/if}
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";
  section {
    @apply border-stronger bg-primary overflow-auto rounded-md border border-b shadow-md;
  }
</style>
