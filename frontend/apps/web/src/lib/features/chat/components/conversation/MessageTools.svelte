<script lang="ts">
  import { IconCopy } from "@intric/icons/copy";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { Button, Tooltip } from "@intric/ui";
  import BlobPreview from "$lib/features/knowledge/components/BlobPreview.svelte";
  import LinkReference from "$lib/features/knowledge/components/LinkReference.svelte";
  import { getFaviconUrlService } from "$lib/features/knowledge/FaviconUrlService.svelte";
  import { getMessageContext } from "../../MessageContext.svelte";

  const { current, isLast } = getMessageContext();
  const message = $derived(current());

  let referencesExpanded = $state(false);
  let showCopiedMessage = $state(false);

  const faviconService = getFaviconUrlService();
  import { m } from "$lib/paraglide/messages";
</script>

<div
  class:showOnHover={true}
  class:md:opacity-0={!referencesExpanded && !isLast()}
  class="mb-6 flex flex-col items-start group-hover/message:opacity-100 md:-mb-2"
>
  <div class="flex gap-2">
    <Tooltip text={m.copy_response()}>
      <Button
        on:click={() => {
          navigator.clipboard.writeText(message.answer);
          showCopiedMessage = true;
          setTimeout(() => {
            showCopiedMessage = false;
          }, 2000);
        }}
        unstyled
        class="border-default hover:bg-hover-stronger flex gap-2 rounded-lg border p-1.5 shadow-sm"
        padding="icon"
        ><IconCopy />
        {#if showCopiedMessage}
          <span class="pr-2">{m.copied()}</span>
        {/if}
      </Button>
    </Tooltip>

    {#if message.references.length > 0 || message.web_search_references.length > 0}
      <Button
        unstyled
        class="border-default hover:bg-hover-dimmer flex gap-1 rounded-lg border p-1.5 pr-2.5 shadow-sm"
        on:click={() => {
          referencesExpanded = !referencesExpanded;
        }}
      >
        <IconChevronRight
          class={referencesExpanded ? "rotate-90 transition-all" : "transition-all"}
        />
        {message.references.length + message.web_search_references.length} {m.references()}
      </Button>
    {/if}
  </div>
  {#if referencesExpanded}
    <div class="mb-2 flex w-full flex-wrap gap-2 pt-2 md:pb-6">
      {#each message.references as reference, index (reference.id)}
        {#if reference.metadata.url}
          <LinkReference blob={reference} index={index + 1} />
        {:else}
          <BlobPreview blob={reference} index={index + 1} />
        {/if}
      {/each}

      {#each message.web_search_references as searchResult (searchResult.id)}
        <a class="hover:bg-hover-default flex items-center gap-2" href={searchResult.url}>
          <img
            src={faviconService.getFavicon(searchResult.url)}
            alt=""
            class="border-default h-6 w-6 rounded-md border p-0.5"
          />
          {searchResult.title}
        </a>
      {/each}
    </div>
  {/if}
</div>
