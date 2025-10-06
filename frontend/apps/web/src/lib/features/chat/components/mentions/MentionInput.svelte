<script lang="ts">
  import { dynamicColour } from "$lib/core/colours";
  import { getMentionInput } from "./MentionInput";

  const {
    elements: { input, suggestionList },
    states: { suggestions, selectedIndex, question },
    insertMentionNode
  } = getMentionInput();

  const {
    ...rest
  }: {
    onpaste?: (event: ClipboardEvent) => void | null | undefined;
  } = $props();
  import { m } from "$lib/paraglide/messages";
</script>

<div class="relative flex-grow">
  <div class="relative max-h-[440px] overflow-y-auto rounded-lg px-2.5 py-2 text-lg">
    <div
      contenteditable="true"
      use:input
      class="min-h-12 whitespace-pre-wrap focus:ring-0 focus:outline-none"
      {...rest}
    ></div>
    {#if $question.length === 0}
      <div class="text-muted pointer-events-none absolute top-2">{m.ask_a_question()}</div>
    {/if}
  </div>
  <div
    class="border-default bg-primary absolute z-[100] mb-10 -ml-3 hidden max-h-[300px] flex-col overflow-y-auto rounded-xl border p-1 text-lg shadow-md"
    use:suggestionList
  >
    {#each $suggestions as item, index (item.id)}
      <button
        onclick={() => insertMentionNode(item)}
        data-selected={$selectedIndex === index}
        {...dynamicColour({ basedOn: item.id })}
        class="mention-list-item hover:bg-dynamic-dimmer hover:text-dynamic-stronger scroll-m-1 rounded-lg p-2 text-left"
        >{item.head}<strong>{item.match}</strong>{item.tail}</button
      >
    {/each}
  </div>
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  :global(.mention) {
    @apply bg-dynamic-dimmer text-dynamic-stronger rounded-full px-2.5 py-1.5 text-base font-medium;
  }
  :global(.mention-list-item[data-selected="true"]) {
    @apply !bg-dynamic-dimmer !text-dynamic-stronger;
  }
</style>
