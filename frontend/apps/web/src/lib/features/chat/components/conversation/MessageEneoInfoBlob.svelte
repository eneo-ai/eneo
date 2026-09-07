<script lang="ts">
  import BlobPreview from "$lib/features/knowledge/components/BlobPreview.svelte";
  import McpResourceSnippetModal from "./McpResourceSnippetModal.svelte";
  import { Tooltip } from "@eneo/ui";
  import type { EneoInrefCustomComponentProps } from "@eneo/ui/components/markdown";
  import { getMessageContext } from "../../MessageContext.svelte";
  import { getFaviconUrlService } from "$lib/features/knowledge/FaviconUrlService.svelte";
  import {
    citedTextDocumentReferences,
    documentNumber,
    mergeAdjacentCitations
  } from "../../mcpReferenceDocs";
  import { m } from "$lib/paraglide/messages";

  let { token }: EneoInrefCustomComponentProps = $props();

  const faviconService = getFaviconUrlService();
  const { current } = getMessageContext();

  const [references, mcpToolReferences] = $derived.by(() => {
    const message = current();
    return [
      message.references,
      // Same filtered list MessageTools numbers its chips over: cited-only,
      // in citation order; image references render as thumbnails and hold
      // no citation number.
      citedTextDocumentReferences(message.mcp_tool_references ?? [], message.answer ?? "")
    ];
  });

  const reference = $derived.by(() => {
    const idx = references.findIndex((ref) => ref.id.startsWith(token.id));
    if (idx > -1)
      return {
        ...references[idx],
        number: idx + 1
      };
  });

  // Chips whose neighbour already cites the same document: rendering them
  // would repeat a number without adding a source, so they fold into that
  // neighbour and hand it their passages.
  const citationMerge = $derived.by(() => {
    const message = current();
    return mergeAdjacentCitations(message.mcp_tool_references ?? [], message.answer ?? "");
  });

  /** Passage separator inside the snippet modal, which renders Markdown. */
  const PASSAGE_BREAK = "\n\n---\n\n";

  type MetaBag = Record<string, unknown> & {
    sourceType?: string;
    title?: string;
    pageRange?: string;
    section?: string;
  };

  const mcpReference = $derived.by(() => {
    if (citationMerge.suppressed.has(token.id)) return;
    const idx = mcpToolReferences.findIndex((ref) => ref.id.startsWith(token.id));
    if (idx > -1) {
      const ref = mcpToolReferences[idx];
      const meta = (ref.meta ?? {}) as MetaBag;
      const sourceType = meta.sourceType;
      const title = meta.title ?? hostFromUri(ref.uri);
      const pageRange = meta.pageRange ?? null;
      const section = meta.section ?? null;
      const labelText = section ? `${title} → ${section}` : title;
      // The snippet carries this passage plus any the folded-away chips beside
      // it would have shown, so collapsing them costs the reader nothing.
      const passages = [ref, ...(citationMerge.absorbedBy.get(token.id) ?? [])]
        .map((passage) => passage.content)
        .filter((content): content is string => !!content);
      return {
        id: ref.id,
        uri: ref.uri,
        content: passages.length ? passages.join(PASSAGE_BREAK) : null,
        title,
        labelText,
        sourceType: sourceType ?? null,
        pageRange,
        section,
        // Number by DOCUMENT, matching the deduped chip list in
        // MessageTools: passages from the same document share one number.
        number: documentNumber(mcpToolReferences, ref)
      };
    }
  });

  function hostFromUri(uri: string): string {
    try {
      return new URL(uri).hostname || uri;
    } catch {
      return uri;
    }
  }
</script>

{#snippet label(number: number, title: string | null | undefined)}
  {number}<span>: {title}</span>
{/snippet}

{#if reference}
  {#if reference.metadata.url}
    <Tooltip text={reference.metadata.url} renderInline>
      <!-- eslint-disable svelte/no-navigation-without-resolve -- external reference URL from message metadata -->
      <a
        href={reference.metadata.url}
        target="_blank"
        rel="noreferrer"
        class={["reference", token.level]}
      >
        {@render label(reference.number, reference.metadata.title)}
      </a>
      <!-- eslint-enable svelte/no-navigation-without-resolve -->
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
{#if mcpReference}
  {#if (mcpReference.sourceType === "crawl-page" || mcpReference.sourceType === "web-search") && /^https?:\/\//i.test(mcpReference.uri)}
    <Tooltip text={mcpReference.title} renderInline>
      <!-- Web pages the answer cites: crawled pages and web-search results
           both render as an external favicon chip linking to the source. -->
      <!-- eslint-disable svelte/no-navigation-without-resolve -- external source URL from MCP reference -->
      <a
        href={mcpReference.uri}
        target="_blank"
        rel="noreferrer"
        class="hover:bg-secondary border-default !m-0 inline-block items-center overflow-clip rounded-lg border align-middle"
        aria-label="{m.favicon_for()} {mcpReference.uri}"
      >
        <span
          class="favicon-bg !m-0 inline-block h-7 w-7 align-middle"
          style:background-image="url({faviconService.getFavicon(mcpReference.uri)})"
          role="img"
          aria-label="{m.favicon_for()} {mcpReference.uri}"
        ></span>
      </a>
      <!-- eslint-enable svelte/no-navigation-without-resolve -->
    </Tooltip>
  {:else}
    <Tooltip text={mcpReference.title} renderInline>
      <McpResourceSnippetModal
        title={mcpReference.title}
        uri={mcpReference.uri}
        content={mcpReference.content}
        pageRange={mcpReference.pageRange}
        section={mcpReference.section}
      >
        {#snippet children({ showSnippet }: { showSnippet: () => void })}
          <button onclick={showSnippet} class={["reference", token.level]}>
            {@render label(mcpReference?.number ?? 0, mcpReference?.labelText ?? "")}
          </button>
        {/snippet}
      </McpResourceSnippetModal>
    </Tooltip>
  {/if}
{/if}

<style lang="postcss">
  @reference "@eneo/ui/styles";
  .block {
    @apply border-b-4 px-3 py-1;
  }

  .inline {
    span {
      @apply hidden;
    }
  }

  .reference {
    @apply border-default bg-secondary hover:bg-hover-stronger ml-1.5 inline-block min-h-7 min-w-7 rounded-lg border border-b-2 px-2 text-center font-mono text-base font-normal no-underline shadow hover:cursor-pointer;
  }

  /* Favicons render as background-image on a span instead of an <img>.
     The Markdown component re-lexes on every streamed token, which causes
     every inref chip to unmount + remount. An <img> remount triggers a
     visible blank/load flash even when the URL is in the browser cache;
     a background-image painted on a fresh element repaints from cache
     synchronously, with no flash. */
  :global(span.favicon-bg) {
    background-repeat: no-repeat;
    background-position: center;
    background-size: 1.25rem 1.25rem;
  }
</style>
