<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getEneo } from "$lib/core/Eneo";
  import { IconRefresh } from "@eneo/icons/refresh";
  import type { Website } from "@eneo/eneo-js";
  import { Button, Dialog } from "@eneo/ui";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  export let website: Website;
  export let isDisabled = false;

  const eneo = getEneo();

  let isProcessing = false;
  let showDialog: Dialog.OpenState;

  async function createRun() {
    isProcessing = true;
    try {
      eneo.websites.crawlRuns.create(website).then(() => {
        isProcessing = false;
        invalidate("crawlruns:list");
      });
      $showDialog = false;
    } catch (error) {
      console.error(error);
      toastError(error, m.error_creating_crawl_run());
    }
  }
</script>

<Dialog.Root bind:isOpen={showDialog}>
  <Dialog.Trigger let:trigger asFragment>
    {#if isDisabled}
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <span {...props} class="block">
              <Button is={trigger} variant="primary" disabled>
                <IconRefresh></IconRefresh>
                {m.sync_now()}</Button
              >
            </span>
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content>{m.cant_sync_while_crawl_running()}</Tooltip.Content>
      </Tooltip.Root>
    {:else}
      <Button is={trigger} variant="primary">
        <IconRefresh></IconRefresh>
        {m.sync_now()}</Button
      >
    {/if}
  </Dialog.Trigger>
  <Dialog.Content width="small">
    <Dialog.Title>{m.sync_website()}</Dialog.Title>
    <Dialog.Description>
      {m.confirm_sync_website({
        websiteName: website.name ? `${website.name} (${website.url})` : website.url
      })}
    </Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="primary" on:click={createRun} disabled={isProcessing}
        >{isProcessing ? m.starting() : m.start_crawl()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
