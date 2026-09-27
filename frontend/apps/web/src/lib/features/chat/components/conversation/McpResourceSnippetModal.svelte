<script lang="ts">
  import type { Snippet } from "svelte";
  import { Markdown } from "$lib/components/markdown/index.js";
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    title: string;
    uri: string;
    content?: string | null;
    pageRange?: string | null;
    section?: string | null;
    children: Snippet<[{ showSnippet: () => void }]>;
  };

  let { title, uri, content = null, pageRange = null, section = null, children }: Props = $props();

  let isOpen = $state(false);

  const showSnippet = () => {
    isOpen = true;
  };

  const isHttp = $derived(/^https?:\/\//i.test(uri));
</script>

<Dialog.Root bind:open={isOpen}>
  {@render children({ showSnippet })}

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{title}</Dialog.Title>
      <Dialog.Description class="sr-only">
        {m.mcp_resource_snippet_description({ title })}
      </Dialog.Description>
    </Dialog.Header>

    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        <div class="flex flex-col gap-3 p-4">
          {#if section || pageRange}
            <div class="text-muted text-sm">
              {#if section}<span>{section}</span>{/if}
              {#if section && pageRange}<span> · </span>{/if}
              {#if pageRange}<span>{m.mcp_resource_page_range({ pageRange })}</span>{/if}
            </div>
          {/if}
          {#if content}
            <Markdown source={content} />
          {:else}
            <p class="text-muted italic">{m.mcp_resource_unknown_source()}</p>
          {/if}
        </div>
      </div>
    </div>

    <Dialog.Footer class={dialogLayout.footer}>
      {#if isHttp}
        <!-- eslint-disable svelte/no-navigation-without-resolve -- external MCP resource URL from upstream tool -->
        <a
          href={uri}
          target="_blank"
          rel="noreferrer"
          class="hover:bg-secondary border-default inline-flex items-center rounded-lg border px-3 py-2 text-sm no-underline"
        >
          {m.mcp_resource_open_external()}
        </a>
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
        <div class="flex-grow"></div>
      {/if}
      <Dialog.Close class={buttonVariants()}>{m.done()}</Dialog.Close>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
