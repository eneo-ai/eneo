<script lang="ts">
  import { fade, fly } from "svelte/transition";
  import { parseTokens } from "../mentions/parseMentions";
  import { parseQuotedQuestion, quotedFileMatches } from "../../questionQuote";
  import { getChatService } from "../../ChatService.svelte";
  import { getFilePreview } from "$lib/features/file-preview/FilePreview.svelte";
  import { getMessageContext } from "../../MessageContext.svelte";
  import { tableLocationLabel } from "$lib/features/file-preview/tableReference";
  import { m } from "$lib/paraglide/messages";

  const { current, isLast, isLoading } = getMessageContext();
  const contents = $derived(current().question);
  // A question may open with a passage quoted from a file preview.
  const parsed = $derived(parseQuotedQuestion(contents));
  let tokens = $derived(parseTokens(parsed.text));

  // New quotes retain the exact file identity. Filename matching is only for
  // legacy quotes, and must never substitute a revision for an exact reference.
  const chat = getChatService();
  const preview = getFilePreview();
  const quotedFile = $derived.by(() => {
    const quote = parsed.quote;
    if (!quote?.fileName || !preview) return null;
    const messages = chat.currentConversation.messages ?? [];
    const own = messages.indexOf(current());
    for (let index = own === -1 ? messages.length - 1 : own; index >= 0; index--) {
      const { generated_files, files } = messages[index];
      const file = [...(generated_files ?? []), ...(files ?? [])].findLast(
        (candidate) => quotedFileMatches(quote, candidate) && preview.canPreview(candidate)
      );
      if (file) return file;
    }
    return null;
  });

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
    {#snippet quoted(quote: NonNullable<typeof parsed.quote>)}
      {@const location = tableLocationLabel(quote.locator, (row) => m.table_reference_row({ row }))}
      <blockquote class="m-0">
        <p class="text-secondary m-0 line-clamp-6 text-base whitespace-pre-wrap">{quote.text}</p>
        {#if quote.fileName}
          <footer class="text-tertiary mt-1 text-xs">
            {quote.fileName}
            {#if location}<span> · {location}</span>{/if}
          </footer>
        {/if}
      </blockquote>
    {/snippet}
    {#if parsed.quote && quotedFile}
      <button
        type="button"
        title={m.file_quote_show({ name: quotedFile.name })}
        onclick={(event) =>
          parsed.quote && preview?.showPassage(quotedFile, parsed.quote, event.currentTarget)}
        class="bg-primary/60 hover:bg-primary focus-visible:ring-accent-default block w-full rounded-xl px-4 py-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none {parsed.text
          ? 'mb-3'
          : ''}"
      >
        {@render quoted(parsed.quote)}
      </button>
    {:else if parsed.quote}
      <div class="bg-primary/60 rounded-xl px-4 py-2.5 {parsed.text ? 'mb-3' : ''}">
        {@render quoted(parsed.quote)}
        {#if parsed.quote.fileId}<p class="text-muted-foreground mt-1 text-xs">
            {m.table_reference_unavailable()}
          </p>{/if}
      </div>
    {/if}
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
  @reference "@eneo/ui/styles";
  :global(.question-mention) {
    @apply bg-hover-default rounded-full px-2 py-1;
  }
</style>
