<script lang="ts">
  import type { InfoBlob } from "@eneo/eneo-js";
  import * as Pagination from "$lib/components/ui/pagination/index.js";
  import { m } from "$lib/paraglide/messages";
  import BlobPreview from "../BlobPreview.svelte";

  type Props = {
    /** The full set of blobs; pagination is applied locally. `undefined` while not yet loaded. */
    blobs: InfoBlob[] | undefined;
    loading?: boolean;
    /** Message shown when loading has finished and there are no blobs. */
    emptyMessage: string;
  };

  let { blobs, loading = false, emptyMessage }: Props = $props();

  const ITEMS_PER_PAGE = 10;

  let currentPage = $state(1);

  const totalPages = $derived(blobs ? Math.ceil(blobs.length / ITEMS_PER_PAGE) : 0);

  const pagedBlobs = $derived.by(() => {
    if (!blobs) return [];
    const start = (currentPage - 1) * ITEMS_PER_PAGE;
    return blobs.slice(start, start + ITEMS_PER_PAGE);
  });

  // Keep the page in range if the underlying list shrinks (e.g. after a refetch).
  $effect(() => {
    if (totalPages > 0 && currentPage > totalPages) {
      currentPage = totalPages;
    }
  });

  function formatBlobSize(bytes: number | undefined): string {
    if (!bytes) return "";
    const kb = bytes / 1024;
    if (kb < 1024) return `${kb.toFixed(1)} KB`;
    return `${(kb / 1024).toFixed(1)} MB`;
  }
</script>

<div class="border-default flex flex-col gap-0.5 border-t px-2 py-1.5">
  {#if loading}
    <div class="text-muted flex items-center gap-2 px-2 py-2 text-sm">{m.loading()}</div>
  {:else if blobs && blobs.length > 0}
    {#each pagedBlobs as blob (blob.id)}
      <BlobPreview {blob} let:showBlob>
        <button
          class="hover:bg-hover-dimmer focus-visible:ring-stronger flex w-full cursor-pointer items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-left text-sm transition-colors focus-visible:ring-2 focus-visible:outline-none"
          onclick={showBlob}
        >
          <span class="flex-grow truncate">
            {blob.metadata?.title || blob.metadata?.url || m.untitled()}
          </span>
          {#if blob.metadata?.size}
            <span class="text-muted flex-shrink-0 text-xs"
              >{formatBlobSize(blob.metadata.size)}</span
            >
          {/if}
        </button>
      </BlobPreview>
    {/each}

    {#if totalPages > 1}
      <Pagination.Root
        count={blobs.length}
        perPage={ITEMS_PER_PAGE}
        bind:page={currentPage}
        class="border-default mt-1 border-t pt-2"
      >
        <Pagination.Content class="justify-center gap-3">
          <Pagination.Item>
            <Pagination.PrevButton>{m.previous()}</Pagination.PrevButton>
          </Pagination.Item>
          <Pagination.Item>
            <span class="text-muted px-1 text-sm">
              {m.page_x_of_y({ x: currentPage, y: totalPages })}
            </span>
          </Pagination.Item>
          <Pagination.Item>
            <Pagination.NextButton>{m.next()}</Pagination.NextButton>
          </Pagination.Item>
        </Pagination.Content>
      </Pagination.Root>
    {/if}
  {:else}
    <div class="text-muted flex items-center gap-2 py-2 text-sm">{emptyMessage}</div>
  {/if}
</div>
