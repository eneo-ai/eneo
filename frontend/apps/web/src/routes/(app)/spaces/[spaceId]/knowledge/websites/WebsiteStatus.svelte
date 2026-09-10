<script lang="ts">
  import type { CrawlResourceFailure, WebsiteSparse } from "@eneo/eneo-js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import CrawlRunStatus from "$lib/features/knowledge/CrawlRunStatus.svelte";
  import CrawlFailureActions from "$lib/features/knowledge/CrawlFailureActions.svelte";
  import { m } from "$lib/paraglide/messages";

  export let website: WebsiteSparse;
  export let onshowFailures: ((kind: CrawlResourceFailure["kind"] | null) => void) | undefined =
    undefined;
</script>

<div class="flex flex-col items-start gap-1">
  {#if website.latest_crawl}
    <CrawlRunStatus run={website.latest_crawl} />
    {#if onshowFailures}
      <CrawlFailureActions run={website.latest_crawl} onselect={onshowFailures} />
    {/if}
  {:else}
    <Badge variant="secondary">{m.not_synced()}</Badge>
  {/if}
</div>
