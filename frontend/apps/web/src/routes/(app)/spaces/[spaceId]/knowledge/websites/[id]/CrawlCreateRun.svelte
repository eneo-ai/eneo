<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getEneo } from "$lib/core/Eneo";
  import { IconRefresh } from "@eneo/icons/refresh";
  import { IconStop } from "@eneo/icons/stop";
  import type { CrawlRun, Website } from "@eneo/eneo-js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { toast } from "$lib/components/toast";

  export let website: Website;
  export let activeRun: CrawlRun | undefined;
  export let hasHistory = false;

  const eneo = getEneo();

  let isStarting = false;
  let isStopping = false;
  let startDialogOpen = false;
  let stopDialogOpen = false;

  $: isStopRequested = activeRun?.phase === "stopping" || isStopping;
  $: websiteName = website.name ? `${website.name} (${website.url})` : website.url;

  async function createRun() {
    isStarting = true;
    try {
      await eneo.websites.crawlRuns.create(website);
      startDialogOpen = false;
      await invalidate("crawlruns:list");
    } catch (error) {
      console.error(error);
      toastError(error, m.error_creating_crawl_run());
    } finally {
      isStarting = false;
    }
  }

  async function stopRun() {
    if (!activeRun) return;

    isStopping = true;
    try {
      await eneo.websites.crawlRuns.cancel(activeRun);
      stopDialogOpen = false;
      toast.success(m.crawl_stopped());
      await invalidate("crawlruns:list");
    } catch (error) {
      console.error(error);
      toastError(error, m.stop_crawl_failed());
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

<AlertDialog.Root bind:open={startDialogOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.sync_website()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.confirm_sync_website({ websiteName })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={isStarting}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action disabled={isStarting} onclick={createRun}>
        {isStarting ? m.starting() : m.start_crawl()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root bind:open={stopDialogOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.stop_crawl_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.stop_crawl_description({ websiteName })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={isStopping}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={isStopping} onclick={stopRun}>
        {isStopping ? m.stopping_crawl() : m.stop_crawl()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
