<script lang="ts">
  import { fade, fly } from "svelte/transition";
  import { parseTokens } from "../mentions/parseMentions";
  import { getMessageContext } from "../../MessageContext.svelte";
  import { m } from "$lib/paraglide/messages";

  const { current, isLast, isLoading } = getMessageContext();
  const contents = $derived(current().question);
  let tokens = $derived(parseTokens(contents));

  const flyIn = (node: HTMLElement) => fly(node, { duration: 700, y: 100 });
  const noAnimation = (node: HTMLElement) => fade(node, { duration: 0 });
  const appearTransition = $derived(isLast() && isLoading() ? flyIn : noAnimation);
</script>

{#if contents}
  <div
    in:appearTransition|global
    class="question prose bg-secondary max-w-full self-end rounded-3xl rounded-br-none px-8 py-4 break-words md:max-w-[85%]"
  >
    <span class="sr-only">{m.question()}</span>
    <p class="m-0 text-lg whitespace-pre-wrap">
      {#each tokens as token (token)}
        {#if token.type === "text"}
          {token.content}
        {:else if token.type === "mention"}
          <span class="question-mention">@{token.handle}</span>
        {/if}
      {/each}
    </p>
  </div>
{/if}

<style lang="postcss">
  @reference "@intric/ui/styles";
  :global(.question-mention) {
    @apply bg-hover-default rounded-full px-2 py-1;
  }
</style>
