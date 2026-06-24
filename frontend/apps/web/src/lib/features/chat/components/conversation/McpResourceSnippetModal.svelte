<script lang="ts">
  import type { Snippet } from "svelte";
  import { writable } from "svelte/store";
  import { Button, Dialog, Markdown } from "@intric/ui";
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

  const openController = writable(false);

  const showSnippet = () => {
    openController.set(true);
  };

  const isHttp = $derived(/^https?:\/\//i.test(uri));
</script>

<Dialog.Root {openController}>
  {@render children({ showSnippet })}

  <Dialog.Content width="medium">
    <Dialog.Title>{title}</Dialog.Title>
    <Dialog.Description hidden>
      {m.mcp_resource_snippet_description({ title })}
    </Dialog.Description>

    <Dialog.Section scrollable>
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
    </Dialog.Section>

    <Dialog.Controls let:close>
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
      <Button variant="primary" is={close}>{m.done()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
