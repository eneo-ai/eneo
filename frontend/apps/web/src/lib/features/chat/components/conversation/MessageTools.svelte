<script lang="ts">
  import {
    copyAssistantAnswer,
    getPreferredAssistantCopyFormat,
    type AssistantCopyFormat
  } from "$lib/features/chat/copyAssistantAnswer";
  import { getAppContext } from "$lib/core/AppContext";
  import { IconCopy } from "@intric/icons/copy";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { Button, Dropdown, Tooltip } from "@intric/ui";
  import BlobPreview from "$lib/features/knowledge/components/BlobPreview.svelte";
  import LinkReference from "$lib/features/knowledge/components/LinkReference.svelte";
  import McpResourceSnippetModal from "./McpResourceSnippetModal.svelte";
  import { getFaviconUrlService } from "$lib/features/knowledge/FaviconUrlService.svelte";
  import { getMessageContext } from "../../MessageContext.svelte";

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

  type MetaBag = Record<string, unknown> & {
    sourceType?: string;
    title?: string;
    pageRange?: string;
    section?: string;
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
      section: meta.section ?? null
    };
  }

  const totalRefs = $derived(
    message.references.length + message.web_search_references.length + mcpRefs.length
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

      {#each mcpRefs as ref (ref.id)}
        {@const info = readMeta(ref)}
        {#if info.sourceType === "crawl-page" && /^https?:\/\//i.test(ref.uri)}
          <!-- eslint-disable svelte/no-navigation-without-resolve -- external MCP crawl-page URL -->
          <a class="hover:bg-hover-default flex items-center gap-2" href={ref.uri}>
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
                class="hover:bg-hover-default border-default flex items-center gap-2 rounded-md border px-2 py-1 text-sm"
                onclick={showSnippet}
              >
                {info.title}{info.section ? ` → ${info.section}` : ""}
              </button>
            {/snippet}
          </McpResourceSnippetModal>
        {/if}
      {/each}
    </div>
  {/if}
</div>
