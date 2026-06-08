<script lang="ts">
  import type { GroupSparse, InfoBlob, WebsiteSparse } from "@intric/intric-js";
  import { IconCancel } from "@intric/icons/cancel";
  import { IconCollections } from "@intric/icons/collections";
  import { IconWeb } from "@intric/icons/web";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { IconTrash } from "@intric/icons/trash";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getIntric } from "$lib/core/Intric";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName";
  import KnowledgeBlobList from "./KnowledgeBlobList.svelte";

  type Props = {
    kind: "collection" | "website";
    item: GroupSparse | WebsiteSparse;
    modelEnabled: boolean;
    onRemove: () => void;
  };

  let { kind, item, modelEnabled, onRemove }: Props = $props();

  const intric = getIntric();

  // The discriminant `kind` decides which view of `item` is valid in each branch.
  const collection = $derived(item as GroupSparse);
  const website = $derived(item as WebsiteSparse);

  const pagesCrawled = $derived(
    kind === "website" ? (website.latest_crawl?.pages_crawled ?? 0) : 0
  );
  const pagesFailed = $derived(kind === "website" ? (website.latest_crawl?.pages_failed ?? 0) : 0);
  const hasFailures = $derived(pagesFailed > 0);

  const title = $derived(kind === "collection" ? collection.name : formatWebsiteName(website));
  const expandable = $derived(
    kind === "collection" ? collection.metadata.num_info_blobs > 0 : pagesCrawled > 0
  );
  const emptyMessage = $derived(
    kind === "collection" ? m.knowledge_no_files_found() : m.noPagesFound()
  );

  let expanded = $state(false);
  let blobs = $state<InfoBlob[] | undefined>(undefined);
  let loading = $state(false);
  let loaded = false;

  async function ensureBlobs() {
    if (loaded || loading) return;
    loading = true;
    try {
      blobs =
        kind === "collection"
          ? await intric.groups.listInfoBlobs(collection)
          : await intric.websites.indexedBlobs.list(website);
      loaded = true;
    } catch (error) {
      console.error(`Failed to fetch blobs for ${kind} ${item.id}:`, error);
    } finally {
      loading = false;
    }
  }

  function onOpenChange(open: boolean) {
    expanded = open;
    if (open) ensureBlobs();
  }
</script>

<Collapsible.Root open={expanded} {onOpenChange} class="w-full">
  <div
    class="border-default hover:bg-hover-dimmer flex h-16 w-full items-center gap-2 border-b px-4"
    class:text-negative-default={!modelEnabled}
    class:bg-orange-50={hasFailures}
    class:dark:bg-orange-950={hasFailures}
  >
    {#if expandable}
      <Collapsible.Trigger
        class="flex size-6 cursor-pointer items-center justify-center transition-opacity hover:opacity-70"
        aria-label={expanded ? m.aria_collapse() : m.aria_expand()}
      >
        {#if expanded}<IconChevronDown />{:else}<IconChevronRight />{/if}
      </Collapsible.Trigger>
    {:else}
      <div class="size-6"></div>
    {/if}

    {#if !modelEnabled}
      <IconCancel />
    {:else if kind === "collection"}
      <IconCollections />
    {:else}
      <IconWeb />
    {/if}

    <Collapsible.Trigger
      class="flex-grow cursor-pointer truncate px-2 text-left hover:underline"
      disabled={!expandable}
    >
      {title}
    </Collapsible.Trigger>

    {#if !modelEnabled}<span>({m.model_disabled()})</span>{/if}

    {#if kind === "website"}
      {#if hasFailures}
        <Badge
          variant="outline"
          class="border-orange-300 text-orange-700 dark:border-orange-600 dark:text-orange-300"
        >
          {m.pages_failed({ count: pagesFailed })}
        </Badge>
      {/if}
      {#if pagesCrawled > 0}
        <Badge variant="outline" class="text-muted font-normal">
          {m.pageCount({ count: pagesCrawled })}
        </Badge>
      {/if}
    {:else if collection.metadata.num_info_blobs > 0}
      <Badge variant="outline" class="text-muted font-normal">
        {collection.metadata.num_info_blobs}
        {m.resource_files()}
      </Badge>
    {:else}
      <Badge variant="outline" class="text-muted font-normal">{m.empty()}</Badge>
    {/if}

    <Button variant="destructive" size="icon" aria-label={m.remove()} onclick={onRemove}>
      <IconTrash />
    </Button>
  </div>

  <Collapsible.Content>
    <KnowledgeBlobList {blobs} {loading} {emptyMessage} />
  </Collapsible.Content>
</Collapsible.Root>
