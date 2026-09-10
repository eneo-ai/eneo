<script lang="ts">
  import type { CrawlResourceFailure, CrawlRun, Eneo } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import dayjs from "dayjs";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import CrawlRunDetailsContent from "./CrawlRunDetailsContent.svelte";
  import { m } from "$lib/paraglide/messages";

  let {
    run,
    open = $bindable(false),
    fetchFailures,
    initialKind = null,
    onrerun
  }: {
    run: CrawlRun;
    open?: boolean;
    fetchFailures?: Eneo["websites"]["crawlRuns"]["failures"];
    initialKind?: CrawlResourceFailure["kind"] | null;
    onrerun?: () => void;
  } = $props();
</script>

<Dialog.Root bind:open>
  <Dialog.Content
    class="flex max-h-[90dvh] sm:max-h-[85vh] flex-col sm:max-w-3xl"
    closeLabel={m.close()}
  >
    <Dialog.Header>
      <Dialog.Title
        >{m.crawl_details_title({
          date: dayjs(run.created_at).format("YYYY-MM-DD HH:mm")
        })}</Dialog.Title
      >
      <Dialog.Description>{m.crawl_details_description()}</Dialog.Description>
    </Dialog.Header>
    <CrawlRunDetailsContent {run} {open} {fetchFailures} {initialKind} />
    {#if onrerun}
      <div class="border-t pt-3">
        <p class="text-secondary mb-2 text-sm">{m.crawl_retry_whole_website_help()}</p>
        <Button
          variant="outline"
          onclick={() => {
            open = false;
            onrerun?.();
          }}>{m.crawl_retry_whole_website()}</Button
        >
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>
