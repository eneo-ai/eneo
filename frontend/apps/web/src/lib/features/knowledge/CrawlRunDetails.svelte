<script lang="ts">
  import type { CrawlRun, Eneo } from "@eneo/eneo-js";
  import dayjs from "dayjs";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import CrawlRunDetailsContent from "./CrawlRunDetailsContent.svelte";
  import { m } from "$lib/paraglide/messages";

  let {
    run,
    open = $bindable(false),
    fetchFailures
  }: {
    run: CrawlRun;
    open?: boolean;
    fetchFailures?: Eneo["websites"]["crawlRuns"]["failures"];
  } = $props();
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="flex max-h-[85vh] flex-col sm:max-w-3xl" closeLabel={m.close()}>
    <Dialog.Header>
      <Dialog.Title
        >{m.crawl_details_title({
          date: dayjs(run.created_at).format("YYYY-MM-DD HH:mm")
        })}</Dialog.Title
      >
      <Dialog.Description>{m.crawl_details_description()}</Dialog.Description>
    </Dialog.Header>
    <CrawlRunDetailsContent {run} {open} {fetchFailures} />
  </Dialog.Content>
</Dialog.Root>
