<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { TriangleAlert } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    getCrawlerActiveInventoryWebsiteLabel,
    isCrawlerActiveInventoryItemRunning
  } from "$lib/features/admin/crawlerActiveInventory";
  import {
    getCrawlerCircuitBreakerResetCopy,
    type CrawlerCircuitBreakerResetCopy
  } from "$lib/features/admin/crawlerCircuitBreakerReset";
  import { getCrawlerTenantWebsiteInventoryDisplayName } from "$lib/features/admin/crawlerTenantWebsiteInventory";
  import {
    CRAWLER_UPDATE_INTERVAL_OPTIONS,
    getCrawlerUpdateIntervalLabel,
    isPausingTransition,
    isResumingTransition,
    type CrawlerUpdateInterval
  } from "$lib/features/admin/crawlerUpdateInterval";
  import type { CrawlerDialogState } from "./crawlerAdminPageState.svelte";

  type Props = {
    dialogs: CrawlerDialogState;
  };

  const { dialogs }: Props = $props();
</script>

<AlertDialog.Root open={dialogs.delete.open} onOpenChange={(v) => (dialogs.delete.open = v)}>
  <AlertDialog.Content>
    {#if dialogs.delete.candidate}
      {@const deleteDisplay = getCrawlerTenantWebsiteInventoryDisplayName(dialogs.delete.candidate)}
      {@const matches = dialogs.delete.confirmInput.trim() === dialogs.delete.candidate.url.trim()}
      <AlertDialog.Header>
        <AlertDialog.Title>
          {m.crawler_website_delete_dialog_title()}
        </AlertDialog.Title>
        <AlertDialog.Description>
          {m.crawler_website_delete_dialog_description({ website: deleteDisplay })}
        </AlertDialog.Description>
      </AlertDialog.Header>
      <div class="flex flex-col gap-2 px-6 pb-2">
        <label for="crawler-delete-confirm" class="text-muted-foreground text-xs">
          {m.crawler_website_delete_dialog_input_label({ url: dialogs.delete.candidate.url })}
        </label>
        <Input
          id="crawler-delete-confirm"
          bind:value={dialogs.delete.confirmInput}
          placeholder={dialogs.delete.candidate.url}
          autocomplete="off"
          disabled={dialogs.delete.busy !== null}
        />
      </div>
      <AlertDialog.Footer class="bg-popover">
        <AlertDialog.Cancel disabled={dialogs.delete.busy !== null}>
          {m.cancel()}
        </AlertDialog.Cancel>
        <AlertDialog.Action
          variant="destructive"
          disabled={!matches || dialogs.delete.busy !== null}
          onclick={() => void dialogs.delete.confirm()}
        >
          {dialogs.delete.busy !== null
            ? m.crawler_website_delete_dialog_busy()
            : m.crawler_website_delete_dialog_confirm()}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    {/if}
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root open={dialogs.abort.open} onOpenChange={(v) => (dialogs.abort.open = v)}>
  <AlertDialog.Content>
    {#if dialogs.abort.candidate}
      {@const candidateIsRunning = isCrawlerActiveInventoryItemRunning(dialogs.abort.candidate)}
      {@const candidateWebsite = getCrawlerActiveInventoryWebsiteLabel(dialogs.abort.candidate)}
      <AlertDialog.Header>
        <AlertDialog.Title>
          {candidateIsRunning
            ? m.crawler_abort_dialog_title_running()
            : m.crawler_abort_dialog_title_queued()}
        </AlertDialog.Title>
        <AlertDialog.Description>
          {candidateIsRunning
            ? m.crawler_abort_dialog_description_running({ website: candidateWebsite })
            : m.crawler_abort_dialog_description_queued({ website: candidateWebsite })}
        </AlertDialog.Description>
      </AlertDialog.Header>
      <AlertDialog.Footer class="bg-popover">
        <AlertDialog.Cancel disabled={dialogs.abort.busy !== null}>{m.cancel()}</AlertDialog.Cancel>
        <AlertDialog.Action
          variant="destructive"
          disabled={dialogs.abort.busy !== null}
          onclick={() => void dialogs.abort.confirm()}
        >
          {dialogs.abort.busy !== null
            ? m.crawler_abort_button_busy()
            : candidateIsRunning
              ? m.crawler_abort_dialog_confirm_running()
              : m.crawler_abort_dialog_confirm_queued()}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    {/if}
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root
  open={dialogs.circuitReset.open}
  onOpenChange={(v) => (dialogs.circuitReset.open = v)}
>
  <AlertDialog.Content>
    {#if dialogs.circuitReset.candidate}
      {@const resetCopy = getCrawlerCircuitBreakerResetCopy(
        dialogs.circuitReset.candidate
      ) satisfies CrawlerCircuitBreakerResetCopy}
      <AlertDialog.Header>
        <AlertDialog.Title>{resetCopy.dialogTitle}</AlertDialog.Title>
        <AlertDialog.Description>
          {resetCopy.dialogDescription}
        </AlertDialog.Description>
      </AlertDialog.Header>
      {#if resetCopy.followupHint}
        <Alert.Root>
          <TriangleAlert aria-hidden="true" />
          <Alert.Description>{resetCopy.followupHint}</Alert.Description>
        </Alert.Root>
      {/if}
      <AlertDialog.Footer class="bg-popover">
        <AlertDialog.Cancel disabled={dialogs.circuitReset.busy !== null}>
          {resetCopy.cancelLabel}
        </AlertDialog.Cancel>
        <AlertDialog.Action
          disabled={dialogs.circuitReset.busy !== null}
          onclick={() => void dialogs.circuitReset.confirm()}
        >
          {dialogs.circuitReset.busy !== null ? resetCopy.busyLabel : resetCopy.confirmLabel}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    {/if}
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root open={dialogs.interval.open} onOpenChange={(v) => (dialogs.interval.open = v)}>
  <AlertDialog.Content>
    {#if dialogs.interval.candidate}
      {@const intervalCurrent = dialogs.interval.candidate.update_interval as CrawlerUpdateInterval}
      {@const intervalWebsite =
        dialogs.interval.candidate.website_name?.trim() ||
        dialogs.interval.candidate.website_url ||
        m.crawler_active_inventory_unknown_website({
          id: dialogs.interval.candidate.website_id.slice(0, 8)
        })}
      {@const intervalSaving = dialogs.interval.busy !== null}
      {@const pausing = isPausingTransition(intervalCurrent, dialogs.interval.draft)}
      {@const resuming = isResumingTransition(intervalCurrent, dialogs.interval.draft)}
      <AlertDialog.Header>
        <AlertDialog.Title>{m.crawler_update_interval_dialog_title()}</AlertDialog.Title>
        <AlertDialog.Description>
          {m.crawler_update_interval_dialog_description({ website: intervalWebsite })}
        </AlertDialog.Description>
      </AlertDialog.Header>
      <div class="flex flex-col gap-3 py-2">
        <p class="text-muted-foreground text-xs">
          {m.crawler_update_interval_current({
            interval: getCrawlerUpdateIntervalLabel(intervalCurrent)
          })}
        </p>
        <Select.Root
          type="single"
          value={dialogs.interval.draft}
          onValueChange={(value) => {
            if (value) dialogs.interval.draft = value as CrawlerUpdateInterval;
          }}
          disabled={intervalSaving}
        >
          <Select.Trigger aria-label={m.crawler_update_interval_dialog_label()}>
            {getCrawlerUpdateIntervalLabel(dialogs.interval.draft)}
          </Select.Trigger>
          <Select.Content>
            {#each CRAWLER_UPDATE_INTERVAL_OPTIONS as option (option)}
              <Select.Item value={option}>
                {getCrawlerUpdateIntervalLabel(option)}
              </Select.Item>
            {/each}
          </Select.Content>
        </Select.Root>
      </div>
      <AlertDialog.Footer class="bg-popover">
        <AlertDialog.Cancel disabled={intervalSaving}>{m.cancel()}</AlertDialog.Cancel>
        <AlertDialog.Action
          disabled={intervalSaving || dialogs.interval.draft === intervalCurrent}
          onclick={() => void dialogs.interval.confirm()}
        >
          {intervalSaving
            ? m.crawler_update_interval_dialog_busy()
            : pausing
              ? m.crawler_update_interval_dialog_confirm_pause()
              : resuming
                ? m.crawler_update_interval_dialog_confirm_resume()
                : m.crawler_update_interval_dialog_confirm()}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    {/if}
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root open={dialogs.retry.open} onOpenChange={(v) => (dialogs.retry.open = v)}>
  <AlertDialog.Content>
    {#if dialogs.retry.candidate}
      {@const retryWebsite =
        dialogs.retry.candidate.website_name?.trim() ||
        dialogs.retry.candidate.website_url ||
        m.crawler_active_inventory_unknown_website({
          id: dialogs.retry.candidate.website_id.slice(0, 8)
        })}
      {@const retrySaving = dialogs.retry.busy !== null}
      <AlertDialog.Header>
        <AlertDialog.Title>{m.crawler_retry_dialog_title()}</AlertDialog.Title>
        <AlertDialog.Description class="text-left">
          {m.crawler_retry_dialog_description_neutral()}
          <span
            class="text-foreground border-border/60 bg-muted/30 mt-2 block rounded-md border px-2 py-1 font-mono text-xs break-all"
            title={retryWebsite}
          >
            {retryWebsite}
          </span>
        </AlertDialog.Description>
      </AlertDialog.Header>
      <AlertDialog.Footer class="bg-popover">
        <AlertDialog.Cancel disabled={retrySaving}>{m.cancel()}</AlertDialog.Cancel>
        <AlertDialog.Action disabled={retrySaving} onclick={() => void dialogs.retry.confirm()}>
          {retrySaving ? m.crawler_retry_button_busy() : m.crawler_retry_dialog_confirm()}
        </AlertDialog.Action>
      </AlertDialog.Footer>
    {/if}
  </AlertDialog.Content>
</AlertDialog.Root>
