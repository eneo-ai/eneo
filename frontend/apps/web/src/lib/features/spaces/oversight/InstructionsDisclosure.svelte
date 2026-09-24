<!--
  An assistant's or app's instructions, collapsed until asked for: they can
  contain personal data, and a page of prompts buries the configuration.
-->
<script lang="ts">
  import { ChevronRight } from "@lucide/svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    /** The assistant's or app's name, which makes each button's name unique. */
    name: string;
    instructions?: string | null;
    open?: boolean;
  };

  let { name, instructions, open = $bindable(false) }: Props = $props();

  const uid = $props.id();
  const hasInstructions = $derived(!!instructions?.trim());
</script>

{#if hasInstructions}
  <div class="flex flex-col gap-2">
    <Button
      variant="outline"
      size="sm"
      class="w-fit max-md:min-h-11"
      aria-expanded={open}
      aria-controls={`${uid}-instructions`}
      aria-label={open
        ? m.admin_spaces_hide_instructions_named({ name })
        : m.admin_spaces_show_instructions_named({ name })}
      onclick={() => (open = !open)}
    >
      <ChevronRight class={open ? "rotate-90" : undefined} aria-hidden="true" />
      {open ? m.admin_spaces_hide_instructions() : m.admin_spaces_show_instructions()}
    </Button>
    <div
      id={`${uid}-instructions`}
      hidden={!open}
      class="border-default bg-secondary text-primary rounded-md border p-3 text-sm break-words whitespace-pre-wrap"
    >
      {instructions}
    </div>
  </div>
{:else}
  <p class="text-secondary text-sm">{m.admin_spaces_no_instructions()}</p>
{/if}
