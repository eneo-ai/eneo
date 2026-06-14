<script lang="ts">
  import { ArrowUp, Square } from "lucide-svelte";
  import { Button, type ButtonProps } from "$lib/components/ui/button/index.js";
  import { cn } from "$lib/utils.js";
  import { m } from "$lib/paraglide/messages";
  import { getPromptInputContext } from "./context";

  let { disabled, class: className, ...restProps }: ButtonProps = $props();

  const promptInput = getPromptInputContext();
  const isBusy = $derived(promptInput.status === "streaming" || promptInput.status === "submitted");
</script>

{#if isBusy}
  <Button
    data-slot="prompt-input-submit"
    size="icon"
    variant="secondary"
    type="button"
    aria-label={m.cancel_your_request()}
    title={m.stop_answer()}
    onclick={() => promptInput.stop()}
    class={cn("size-9 rounded-lg", className)}
    {...restProps}
  >
    <Square class="size-4" />
  </Button>
{:else}
  <Button
    data-slot="prompt-input-submit"
    size="icon"
    type="submit"
    {disabled}
    aria-label={m.submit_your_question()}
    title={m.send()}
    class={cn("size-9 rounded-lg", className)}
    {...restProps}
  >
    <ArrowUp class="size-5" />
  </Button>
{/if}
