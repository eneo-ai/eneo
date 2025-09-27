<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { IconRefresh } from "@intric/icons/refresh";
  import type { Website } from "@intric/intric-js";
  import { Button, Dialog, Tooltip } from "@intric/ui";

  export let website: Website;
  export let isDisabled = false;

  const intric = getIntric();

  let isProcessing = false;
  let showDialog: Dialog.OpenState;
  let errorMessage = "";
  let successMessage = "";

  async function createRun() {
    isProcessing = true;
    errorMessage = "";
    successMessage = "";

    try {
      await intric.websites.crawlRuns.create(website);

      // Success
      successMessage = "Crawl started successfully! The website will be processed in the background.";
      invalidate("crawlruns:list");

      // Close dialog after a short delay to show success message
      setTimeout(() => {
        $showDialog = false;
        successMessage = "";
      }, 2000);

    } catch (error) {
      console.error("Crawl creation error:", error);

      // Provide user-friendly error messages based on error type
      if (error instanceof Error) {
        if (error.message.includes("403")) {
          errorMessage = "Access denied. You may not have permission to crawl this website.";
        } else if (error.message.includes("404")) {
          errorMessage = "Website not found. Please check if the URL is correct.";
        } else if (error.message.includes("429")) {
          errorMessage = "Too many requests. Please wait a few minutes before trying again.";
        } else if (error.message.includes("network") || error.message.includes("fetch")) {
          errorMessage = "Network error. Please check your internet connection and try again.";
        } else {
          errorMessage = `Failed to start crawl: ${error.message}`;
        }
      } else {
        errorMessage = "An unexpected error occurred. Please try again or contact support.";
      }

    } finally {
      isProcessing = false;
    }
  }
</script>

<Dialog.Root bind:isOpen={showDialog}>
  <Dialog.Trigger let:trigger asFragment>
    <Tooltip text={isDisabled ? "Can't sync while a crawl is already running" : undefined}>
      <Button is={trigger} variant="primary" disabled={isDisabled}>
        <IconRefresh></IconRefresh>
        Sync now</Button
      >
    </Tooltip>
  </Dialog.Trigger>
  <Dialog.Content width="small">
    <Dialog.Title>Sync website</Dialog.Title>

    {#if successMessage}
      <div class="bg-green-50 border border-green-200 text-green-800 px-3 py-2 rounded-md mb-4">
        <p class="text-sm font-medium">✓ {successMessage}</p>
      </div>
    {:else if errorMessage}
      <div class="bg-red-50 border border-red-200 text-red-800 px-3 py-2 rounded-md mb-4">
        <p class="text-sm font-medium">⚠ {errorMessage}</p>
      </div>
    {:else}
      <Dialog.Description>
        Do you want to synchronise
        <span class="italic">
          {website.name ? `${website.name} (${website.url})` : website.url}
        </span> now by starting a new crawl run?

        <br><br>
        <span class="text-sm text-gray-600">
          The crawl will run in the background and may take several minutes depending on website size.
          {#if website.requires_auth}
            This website requires authentication which will be used automatically.
          {/if}
        </span>
      </Dialog.Description>
    {/if}

    <Dialog.Controls let:close>
      <Button is={close} disabled={isProcessing}>Cancel</Button>
      <Button
        variant="primary"
        on:click={createRun}
        disabled={isProcessing || !!successMessage}
      >
        {#if isProcessing}
          Starting...
        {:else if successMessage}
          Started
        {:else}
          Start crawl
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
