<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getEneo } from "$lib/core/Eneo";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { IconStop } from "@eneo/icons/stop";
  import type { CrawlRun, Website } from "@eneo/eneo-js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";

  export let website: Website;
  export let activeRun: CrawlRun | undefined;
  export let hasHistory = false;

  const eneo = getEneo();

  let isStarting = false;
  let isStopping = false;
  export let startDialogOpen = false;
  let stopDialogOpen = false;

  $: isStopRequested = activeRun?.phase === "stopping" || isStopping;
  $: websiteName = website.name ? `${website.name} (${website.url})` : website.url;

  async function createRun() {
    isStarting = true;
    try {
      await eneo.websites.crawlRuns.create(website);
      await invalidate("crawlruns:list");
    } finally {
      isStarting = false;
    }
  }

  async function stopRun() {
    if (!activeRun) return;

    isStopping = true;
    try {
      await eneo.websites.crawlRuns.cancel(activeRun);
      toast.success(m.crawl_stopped());
      await invalidate("crawlruns:list");
    } finally {
      isStopping = false;
    }
  }
</script>

{#if activeRun}
  <Button
    variant="destructive"
    disabled={isStopRequested}
    aria-busy={isStopping}
    onclick={() => (stopDialogOpen = true)}
  >
    <IconStop />
    {isStopRequested ? m.stopping_crawl() : m.stop_crawl()}
  </Button>
{:else}
  <Button disabled={isStarting} aria-busy={isStarting} onclick={() => (startDialogOpen = true)}>
    <IconRefresh />
    {isStarting ? m.starting() : hasHistory ? m.run_crawl_again() : m.sync_now()}
  </Button>
{/if}

<ConfirmDialog
  bind:open={startDialogOpen}
  title={m.sync_website()}
  description={m.confirm_sync_website({ websiteName })}
  confirmLabel={m.start_crawl()}
  pendingLabel={m.starting()}
  variant="default"
  errorContext={m.error_creating_crawl_run()}
  onConfirm={createRun}
/>

<ConfirmDialog
  bind:open={stopDialogOpen}
  title={m.stop_crawl_title()}
  description={m.stop_crawl_description({ websiteName })}
  confirmLabel={m.stop_crawl()}
  pendingLabel={m.stopping_crawl()}
  errorContext={m.stop_crawl_failed()}
  onConfirm={stopRun}
/>
