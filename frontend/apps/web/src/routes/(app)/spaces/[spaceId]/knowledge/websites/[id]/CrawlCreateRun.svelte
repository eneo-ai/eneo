<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { IconRefresh } from "@intric/icons/refresh";
  import type { Website } from "@intric/intric-js";
  import { Button, Dialog, Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let website: Website;
  export let isDisabled = false;

  const intric = getIntric();

  let isProcessing = false;
  let showDialog: Dialog.OpenState;

  async function createRun() {
    isProcessing = true;
    try {
      intric.websites.crawlRuns.create(website).then(() => {
        isProcessing = false;
        invalidate("crawlruns:list");
      });
      $showDialog = false;
    } catch (error) {
      console.error(error);
      alert(m.error_creating_crawl_run());
    }
  }
</script>

<Dialog.Root bind:isOpen={showDialog}>
  <Dialog.Trigger let:trigger asFragment>
    <Tooltip text={isDisabled ? m.cant_sync_while_crawl_running() : undefined}>
      <Button is={trigger} variant="primary" disabled={isDisabled}>
        <IconRefresh></IconRefresh>
        {m.sync_now()}</Button
      >
    </Tooltip>
  </Dialog.Trigger>
  <Dialog.Content width="small">
    <Dialog.Title>{m.sync_website()}</Dialog.Title>
    <Dialog.Description>
      {m.confirm_sync_website({ websiteName: website.name ? `${website.name} (${website.url})` : website.url })}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" on:click={createRun} disabled={isProcessing}
        >{isProcessing ? m.starting() : m.start_crawl()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
