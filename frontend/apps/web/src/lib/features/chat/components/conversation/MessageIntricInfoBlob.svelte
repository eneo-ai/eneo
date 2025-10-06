<script lang="ts">
  import BlobPreview from "$lib/features/knowledge/components/BlobPreview.svelte";
  import { Tooltip } from "@intric/ui";
  import type { IntricInrefCustomComponentProps } from "@intric/ui/components/markdown";
  import { getMessageContext } from "../../MessageContext.svelte";
  import { getFaviconUrlService } from "$lib/features/knowledge/FaviconUrlService.svelte";
  import { m } from "$lib/paraglide/messages";

  let { token }: IntricInrefCustomComponentProps = $props();

  const faviconService = getFaviconUrlService();
  const { current } = getMessageContext();

  const [references, webSearchResults] = $derived.by(() => {
    const message = current();
    return [message.references, message.web_search_references];
  });

  const reference = $derived.by(() => {
    const idx = references.findIndex((ref) => ref.id.startsWith(token.id));
    if (idx > -1)
      return {
        ...references[idx],
        number: idx + 1
      };
  });

  const webReference = $derived.by(() => {
    const idx = webSearchResults.findIndex((ref) => ref.id.startsWith(token.id));
    if (idx > -1)
      return {
        ...webSearchResults[idx],
        number: idx + 1
      };
  });
</script>

{#snippet label(number: number, title: string | null | undefined)}
  {number}<span>: {title}</span>
{/snippet}

{#if reference}
  {#if reference.metadata.url}
    <Tooltip text={reference.metadata.url} renderInline>
      <a
        href={reference.metadata.url}
        target="_blank"
        rel="noreferrer"
        class={["reference", token.level]}
      >
        {@render label(reference.number, reference.metadata.title)}
      </a>
    </Tooltip>
  {:else}
    <Tooltip text={reference.metadata.title ?? undefined} renderInline>
      <BlobPreview blob={reference} let:showBlob>
        <button onclick={showBlob} class={["reference", token.level]}>
          {@render label(reference.number, reference.metadata.title)}
        </button>
      </BlobPreview>
    </Tooltip>
  {/if}
{/if}
{#if webReference}
  <Tooltip text={webReference.title} renderInline>
    <a
      href={webReference.url}
      target="_blank"
      rel="noreferrer"
      class="hover:bg-secondary border-default !m-0 inline-block items-center overflow-clip rounded-lg border align-middle"
    >
      <img
        src={faviconService.getFavicon(webReference.url)}
        alt="{m.favicon_for()} {webReference.url}"
        class="!m-0 h-7 w-7 p-0.5"
      />
    </a>
  </Tooltip>
{/if}

<style lang="postcss">
  @reference "@intric/ui/styles";
  .block {
    @apply border-b-4 px-3 py-1;
  }

  .inline {
    span {
      @apply hidden;
    }
  }

  .reference {
    @apply border-default bg-secondary hover:bg-hover-stronger inline-block min-h-7 min-w-7 rounded-lg border border-b-2 px-2 text-center font-mono text-base font-normal no-underline shadow hover:cursor-pointer;
  }
</style>
