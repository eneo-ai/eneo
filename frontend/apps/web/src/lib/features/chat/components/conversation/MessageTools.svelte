<script lang="ts">
  import {
    copyAssistantAnswer,
    getPreferredAssistantCopyFormat,
    type AssistantCopyFormat
  } from "$lib/features/chat/copyAssistantAnswer";
  import { getAppContext } from "$lib/core/AppContext";
  import { IconCopy } from "@eneo/icons/copy";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconChevronRight } from "@eneo/icons/chevron-right";
  import { Button, Dropdown, Tooltip } from "@eneo/ui";
  import BlobPreview from "$lib/features/knowledge/components/BlobPreview.svelte";
  import LinkReference from "$lib/features/knowledge/components/LinkReference.svelte";
  import McpResourceSnippetModal from "./McpResourceSnippetModal.svelte";
  import { getFaviconUrlService } from "$lib/features/knowledge/FaviconUrlService.svelte";
  import { getMessageContext } from "../../MessageContext.svelte";
  import { dedupeByDocument } from "../../mcpReferenceDocs";
  import type { InfoBlob } from "@eneo/eneo-js";

  const { settings } = getAppContext();
  const { current, isLast } = getMessageContext();
  const message = $derived(current());
  const preferredCopyFormat = $derived(getPreferredAssistantCopyFormat(settings));

  let referencesExpanded = $state(false);
  let showCopiedMessage = $state(false);

  const faviconService = getFaviconUrlService();
  import { m } from "$lib/paraglide/messages";
  // Image references (resource_link blocks with an image mimeType) render as a
  // thumbnail strip in MessageAnswer, not as text-snippet chips here. Exclude
  // them so they neither show as "unknown source" rows nor inflate the count.
  const mcpRefs = $derived(
    (message.mcp_tool_references ?? []).filter((ref) => !(ref.mime_type ?? "").startsWith("image/"))
  );
  // One chip per document: several passages from the same document (chunk
  // fragments of one uri) collapse to a single reference entry.
  const mcpRefDocs = $derived(dedupeByDocument(mcpRefs));

  type MetaBag = Record<string, unknown> & {
    sourceType?: string;
    title?: string;
    pageRange?: string;
    section?: string;
    info_blob_id?: string;
  };

  function readMeta(ref: (typeof mcpRefs)[number]) {
    const meta = (ref.meta ?? {}) as MetaBag;
    let host = ref.uri;
    try {
      host = new URL(ref.uri).hostname || ref.uri;
    } catch {
      /* leave as URI */
    }
    return {
      sourceType: meta.sourceType ?? null,
      title: meta.title ?? host,
      pageRange: meta.pageRange ?? null,
      section: meta.section ?? null,
      infoBlobId: typeof meta.info_blob_id === "string" ? meta.info_blob_id : null
    };
  }

  // A reference that points at an eneo document can open the full document
  // viewer (lazy fetch by id) instead of the stored snippet capture.
  function blobForRef(infoBlobId: string, title: string): InfoBlob {
    return { id: infoBlobId, metadata: { title } } as unknown as InfoBlob;
  }

  const totalRefs = $derived(
    message.references.length + message.web_search_references.length + mcpRefDocs.length
  );

  async function handleCopy(format: AssistantCopyFormat = preferredCopyFormat) {
    await copyAssistantAnswer(message.answer, format);
    showCopiedMessage = true;
    setTimeout(() => {
      showCopiedMessage = false;
    }, 2000);
  }
</script>

<div
  class:showOnHover={true}
  class:md:opacity-0={!referencesExpanded && !isLast()}
  class="mb-6 flex flex-col items-start group-hover/message:opacity-100 md:-mb-2"
>
  <div class="flex gap-2">
    <div class="flex gap-[1px]">
      <Tooltip
        text={preferredCopyFormat === "richtext" ? m.copy_as_richtext() : m.copy_as_markdown()}
      >
        <Button
          on:click={() => handleCopy()}
          unstyled
          class="border-default hover:bg-hover-stronger flex gap-2 rounded-l-lg border p-1.5 shadow-sm"
          padding="icon"
          ><IconCopy />
          {#if showCopiedMessage}
            <span class="pr-2">{m.copied()}</span>
          {/if}
        </Button>
      </Tooltip>
      <Dropdown.Root gutter={2} arrowSize={0} placement="bottom-end">
        <Dropdown.Trigger asFragment let:trigger>
          <Button
            is={trigger}
            unstyled
            class="border-default hover:bg-hover-stronger rounded-r-lg border p-1.5 shadow-sm"
            padding="icon"
            aria-label={m.copy_response_options()}
          >
            <IconChevronDown />
          </Button>
        </Dropdown.Trigger>
        <Dropdown.Menu let:item>
          <Button is={item} onclick={() => handleCopy("markdown")}>
            {m.copy_as_markdown()}
          </Button>
          <Button is={item} onclick={() => handleCopy("richtext")}>
            {m.copy_as_richtext()}
          </Button>
        </Dropdown.Menu>
      </Dropdown.Root>

      {#if totalRefs > 0}
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
          {totalRefs}
          {m.references()}
        </Button>
      {/if}
    </div>
  </div>
  {#snippet docBadge(number: number)}
    <!-- Mirrors the inline citation pill so a pill's number visibly maps to
         its chip; same look as the numbered legacy reference chips. -->
    <span
      class="border-default bg-secondary min-h-6 min-w-6 rounded-md border border-b-2 text-center font-mono text-xs leading-6 font-normal"
      aria-hidden="true"
    >
      {number}
    </span>
  {/snippet}
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
        <!-- eslint-disable svelte/no-navigation-without-resolve -- external web search result URL -->
        <a class="hover:bg-hover-default flex items-center gap-2" href={searchResult.url}>
          <span
            class="favicon-bg border-default inline-block h-6 w-6 rounded-md border p-0.5"
            style:background-image="url({faviconService.getFavicon(searchResult.url)})"
            aria-hidden="true"
          ></span>
          {searchResult.title}
        </a>
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      {/each}

      {#each mcpRefDocs as ref, docIndex (ref.id)}
        {@const info = readMeta(ref)}
        {@const docNumber = docIndex + 1}
        {#if info.infoBlobId}
          <BlobPreview blob={blobForRef(info.infoBlobId, info.title)} let:showBlob>
            <button
              type="button"
              class="hover:bg-hover-default border-default flex items-center gap-2 rounded-md border py-1 pr-2 pl-1 text-sm"
              onclick={showBlob}
            >
              {@render docBadge(docNumber)}
              {info.title}
            </button>
          </BlobPreview>
        {:else if info.sourceType === "crawl-page" && /^https?:\/\//i.test(ref.uri)}
          <!-- eslint-disable svelte/no-navigation-without-resolve -- external MCP crawl-page URL -->
          <a class="hover:bg-hover-default flex items-center gap-2" href={ref.uri}>
            {@render docBadge(docNumber)}
            <span
              class="favicon-bg border-default inline-block h-6 w-6 rounded-md border p-0.5"
              style:background-image="url({faviconService.getFavicon(ref.uri)})"
              aria-hidden="true"
            ></span>
            {info.title}
          </a>
          <!-- eslint-enable svelte/no-navigation-without-resolve -->
        {:else}
          <McpResourceSnippetModal
            title={info.title}
            uri={ref.uri}
            content={ref.content}
            pageRange={info.pageRange}
            section={info.section}
          >
            {#snippet children({ showSnippet }: { showSnippet: () => void })}
              <button
                type="button"
                class="hover:bg-hover-default border-default flex items-center gap-2 rounded-md border py-1 pr-2 pl-1 text-sm"
                onclick={showSnippet}
              >
                {@render docBadge(docNumber)}
                {info.title}{info.section ? ` → ${info.section}` : ""}
              </button>
            {/snippet}
          </McpResourceSnippetModal>
        {/if}
      {/each}
    </div>
  {/if}
</div>
