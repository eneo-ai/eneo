<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
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
  import {
    CRAWLER_UPDATE_INTERVAL_OPTIONS,
    getCrawlerUpdateIntervalLabel,
    isPausingTransition,
    isResumingTransition,
    type CrawlerUpdateInterval
  } from "$lib/features/admin/crawlerUpdateInterval";
  import type { CrawlerDialogState } from "./crawlerAdminPageState.svelte";
  import CrawlerConfirmDialog from "./CrawlerConfirmDialog.svelte";

  type Props = {
    dialogs: CrawlerDialogState;
  };

  const { dialogs }: Props = $props();

  const deleteUrl = $derived(dialogs.delete.candidate?.url ?? "");
  const deleteInputTrimmed = $derived(dialogs.delete.confirmInput.trim());
  const deleteMatches = $derived(deleteUrl !== "" && deleteInputTrimmed === deleteUrl.trim());
  const deleteInputDirty = $derived(deleteInputTrimmed.length > 0);
  const deleteInputInvalid = $derived(deleteInputDirty && !deleteMatches);
  const deleteBusy = $derived(dialogs.delete.busy !== null);

  const abortIsRunning = $derived(
    dialogs.abort.candidate !== null && isCrawlerActiveInventoryItemRunning(dialogs.abort.candidate)
  );
  const abortTarget = $derived(
    dialogs.abort.candidate ? getCrawlerActiveInventoryWebsiteLabel(dialogs.abort.candidate) : null
  );

  const resetCopy = $derived<CrawlerCircuitBreakerResetCopy | null>(
    dialogs.circuitReset.candidate
      ? getCrawlerCircuitBreakerResetCopy(dialogs.circuitReset.candidate)
      : null
  );
  const resetTarget = $derived(
    dialogs.circuitReset.candidate
      ? dialogs.circuitReset.candidate.website_url?.trim() ||
          dialogs.circuitReset.candidate.website_name?.trim() ||
          null
      : null
  );

  const intervalCurrent = $derived<CrawlerUpdateInterval | null>(
    (dialogs.interval.candidate?.update_interval as CrawlerUpdateInterval | undefined) ?? null
  );
  const intervalTarget = $derived(
    dialogs.interval.candidate
      ? dialogs.interval.candidate.website_name?.trim() ||
          dialogs.interval.candidate.website_url ||
          m.crawler_active_inventory_unknown_website({
            id: dialogs.interval.candidate.website_id.slice(0, 8)
          })
      : null
  );
  const intervalPausing = $derived(
    intervalCurrent !== null && isPausingTransition(intervalCurrent, dialogs.interval.draft)
  );
  const intervalResuming = $derived(
    intervalCurrent !== null && isResumingTransition(intervalCurrent, dialogs.interval.draft)
  );
  const intervalSaving = $derived(dialogs.interval.busy !== null);
  const intervalUnchanged = $derived(
    intervalCurrent === null || dialogs.interval.draft === intervalCurrent
  );

  const retryTarget = $derived(
    dialogs.retry.candidate
      ? dialogs.retry.candidate.website_name?.trim() ||
          dialogs.retry.candidate.website_url ||
          m.crawler_active_inventory_unknown_website({
            id: dialogs.retry.candidate.website_id.slice(0, 8)
          })
      : null
  );
</script>

<CrawlerConfirmDialog
  open={dialogs.delete.open}
  onOpenChange={(v) => (dialogs.delete.open = v)}
  title={m.crawler_website_delete_dialog_title()}
  description={m.crawler_website_delete_dialog_description()}
  target={deleteUrl || null}
  variant="destructive"
  confirmLabel={m.crawler_website_delete_dialog_confirm()}
  busyLabel={m.crawler_website_delete_dialog_busy()}
  busy={deleteBusy}
  confirmDisabled={!deleteMatches}
  onConfirm={() => void dialogs.delete.confirm()}
>
  <Field.FieldGroup>
    <Field.Field data-invalid={deleteInputInvalid ? true : undefined}>
      <Field.FieldLabel for="crawler-delete-confirm" class="text-xs">
        {m.crawler_website_delete_dialog_input_label()}
      </Field.FieldLabel>
      <Input
        id="crawler-delete-confirm"
        bind:value={dialogs.delete.confirmInput}
        placeholder={deleteUrl}
        autocomplete="off"
        spellcheck={false}
        disabled={deleteBusy}
        aria-invalid={deleteInputInvalid ? true : undefined}
        aria-describedby="crawler-delete-confirm-hint"
      />
      <Field.FieldDescription id="crawler-delete-confirm-hint">
        {#if deleteMatches}
          <span class="text-positive-stronger">
            {m.crawler_website_delete_dialog_input_match()}
          </span>
        {:else if deleteInputInvalid}
          {m.crawler_website_delete_dialog_input_mismatch()}
        {:else}
          {m.crawler_website_delete_dialog_input_hint()}
        {/if}
      </Field.FieldDescription>
    </Field.Field>
  </Field.FieldGroup>
</CrawlerConfirmDialog>

<CrawlerConfirmDialog
  open={dialogs.abort.open}
  onOpenChange={(v) => (dialogs.abort.open = v)}
  title={abortIsRunning
    ? m.crawler_abort_dialog_title_running()
    : m.crawler_abort_dialog_title_queued()}
  description={abortIsRunning
    ? m.crawler_abort_dialog_description_running()
    : m.crawler_abort_dialog_description_queued()}
  target={abortTarget}
  variant="destructive"
  confirmLabel={abortIsRunning
    ? m.crawler_abort_dialog_confirm_running()
    : m.crawler_abort_dialog_confirm_queued()}
  busyLabel={m.crawler_abort_button_busy()}
  busy={dialogs.abort.busy !== null}
  onConfirm={() => void dialogs.abort.confirm()}
/>

<CrawlerConfirmDialog
  open={dialogs.circuitReset.open}
  onOpenChange={(v) => (dialogs.circuitReset.open = v)}
  title={resetCopy?.dialogTitle ?? ""}
  description={resetCopy?.dialogDescription ?? ""}
  target={resetTarget}
  confirmLabel={resetCopy?.confirmLabel ?? ""}
  busyLabel={resetCopy?.busyLabel ?? ""}
  cancelLabel={resetCopy?.cancelLabel ?? m.cancel()}
  busy={dialogs.circuitReset.busy !== null}
  onConfirm={() => void dialogs.circuitReset.confirm()}
>
  {#if resetCopy?.followupHint}
    <Alert.Root>
      <TriangleAlert aria-hidden="true" />
      <Alert.Description>{resetCopy.followupHint}</Alert.Description>
    </Alert.Root>
  {/if}
</CrawlerConfirmDialog>

<CrawlerConfirmDialog
  open={dialogs.interval.open}
  onOpenChange={(v) => (dialogs.interval.open = v)}
  title={m.crawler_update_interval_dialog_title()}
  description={m.crawler_update_interval_dialog_description()}
  target={intervalTarget}
  confirmLabel={intervalPausing
    ? m.crawler_update_interval_dialog_confirm_pause()
    : intervalResuming
      ? m.crawler_update_interval_dialog_confirm_resume()
      : m.crawler_update_interval_dialog_confirm()}
  busyLabel={m.crawler_update_interval_dialog_busy()}
  busy={intervalSaving}
  confirmDisabled={intervalUnchanged}
  onConfirm={() => void dialogs.interval.confirm()}
>
  <Field.FieldGroup>
    <Field.Field>
      <Field.FieldLabel for="crawler-interval-select" class="text-muted-foreground text-xs">
        {m.crawler_update_interval_current({
          interval: intervalCurrent !== null ? getCrawlerUpdateIntervalLabel(intervalCurrent) : "—"
        })}
      </Field.FieldLabel>
      <Select.Root
        type="single"
        value={dialogs.interval.draft}
        onValueChange={(value) => {
          if (value) dialogs.interval.draft = value as CrawlerUpdateInterval;
        }}
        disabled={intervalSaving}
      >
        <Select.Trigger
          id="crawler-interval-select"
          aria-label={m.crawler_update_interval_dialog_label()}
        >
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
    </Field.Field>
  </Field.FieldGroup>
</CrawlerConfirmDialog>

<CrawlerConfirmDialog
  open={dialogs.retry.open}
  onOpenChange={(v) => (dialogs.retry.open = v)}
  title={m.crawler_retry_dialog_title()}
  description={m.crawler_retry_dialog_description_neutral()}
  target={retryTarget}
  confirmLabel={m.crawler_retry_dialog_confirm()}
  busyLabel={m.crawler_retry_button_busy()}
  busy={dialogs.retry.busy !== null}
  onConfirm={() => void dialogs.retry.confirm()}
/>
