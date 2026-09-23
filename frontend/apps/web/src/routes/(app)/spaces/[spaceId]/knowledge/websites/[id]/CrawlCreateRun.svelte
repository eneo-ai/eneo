<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getEneo } from "$lib/core/Eneo";
  import { IconRefresh } from "@eneo/icons/refresh";
  import type { Website } from "@eneo/eneo-js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  export let website: Website;
  export let isDisabled = false;

  const eneo = getEneo();

  let isProcessing = false;
  let showDialog = false;

  async function createRun() {
    isProcessing = true;
    try {
      eneo.websites.crawlRuns.create(website).then(() => {
        isProcessing = false;
        invalidate("crawlruns:list");
      });
      showDialog = false;
    } catch (error) {
      console.error(error);
      toastError(error, m.error_creating_crawl_run());
    }
  }
</script>

<Dialog.Root bind:open={showDialog}>
  {#if isDisabled}
    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <span {...props} class="block">
            <Button disabled>
              <IconRefresh></IconRefresh>
              {m.sync_now()}</Button
            >
          </span>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content>{m.cant_sync_while_crawl_running()}</Tooltip.Content>
    </Tooltip.Root>
  {:else}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props}>
          <IconRefresh></IconRefresh>
          {m.sync_now()}</Button
        >
      {/snippet}
    </Dialog.Trigger>
  {/if}
  <Dialog.Content class={dialogLayout.content()} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.sync_website()}</Dialog.Title>
      <Dialog.Description>
        {m.confirm_sync_website({
          websiteName: website.name ? `${website.name} (${website.url})` : website.url
        })}
      </Dialog.Description>
    </Dialog.Header>
    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Button onclick={createRun} disabled={isProcessing}
        >{isProcessing ? m.starting() : m.start_crawl()}</Button
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
