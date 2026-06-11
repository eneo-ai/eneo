<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Check, Copy, Sparkles } from "lucide-svelte";
  import { fade } from "svelte/transition";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    /** The extracted final prompt text — applied to the assistant on click. */
    prompt: string;
    /** Disables Apply while a stream is still in flight (matches old behavior). */
    disabled?: boolean;
    /** Called with `prompt` when the user clicks "Use as instructions". */
    onApply: (text: string) => void;
  };

  let { prompt, disabled = false, onApply }: Props = $props();
  let copied = $state(false);

  async function copyToClipboard() {
    if (!prompt) return;
    try {
      await navigator.clipboard.writeText(prompt);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      // Clipboard can be unavailable (insecure context / permissions); the
      // Apply button is the primary path, so silently no-op here.
    }
  }
</script>

<div
  class="border-default bg-subtle flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2.5"
  transition:fade={{ duration: 150 }}
>
  <div class="bg-secondary grid size-8 shrink-0 place-items-center rounded-full">
    <Sparkles class="text-primary size-4" aria-hidden="true" />
  </div>
  <div class="min-w-0 flex-1">
    <div class="text-default text-sm font-medium">{m.prompt_guide_final_prompt_label()}</div>
    <div class="text-muted text-xs">{m.prompt_guide_final_prompt_hint()}</div>
  </div>
  <Button variant="outline" size="sm" onclick={copyToClipboard}>
    {#if copied}
      <Check class="size-3.5" />
      {m.copied()}
    {:else}
      <Copy class="size-3.5" />
      {m.copy()}
    {/if}
  </Button>
  <Button size="sm" {disabled} onclick={() => onApply(prompt)}>
    {m.prompt_guide_apply_button()}
  </Button>
</div>
