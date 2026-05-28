<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { ChevronDown, FileText } from "lucide-svelte";
  import { slide } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    /** Captured prompt text at modal-open time. Empty string hides the card. */
    text: string;
  };

  let { text }: Props = $props();
  let expanded = $state(false);
</script>

{#if text}
  <div class="border-default bg-subtle overflow-hidden rounded-lg border">
    <button
      type="button"
      class="hover:bg-hover-dimmer flex w-full items-center gap-2 px-3 py-2 text-left transition-colors"
      aria-expanded={expanded}
      onclick={() => (expanded = !expanded)}
    >
      <FileText class="text-muted size-4 shrink-0" aria-hidden="true" />
      <span class="text-default flex-1 text-sm font-medium"
        >{m.prompt_guide_current_prompt_label()}</span
      >
      <ChevronDown
        class="text-muted size-4 shrink-0 transition-transform {expanded ? 'rotate-180' : ''}"
        aria-hidden="true"
      />
    </button>
    {#if expanded}
      <div class="border-default border-t px-3 py-2" transition:slide={{ duration: 150 }}>
        <p class="text-secondary max-h-32 overflow-y-auto text-xs whitespace-pre-wrap">
          {text}
        </p>
      </div>
    {/if}
  </div>
{/if}
