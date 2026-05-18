<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).
    See the LICENSE file at the repository root for the full license text.
-->

<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { TriangleAlert } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS,
    canSubmitCrawlerBulkIntervalSelection,
    getCrawlerBulkIntervalFailedPreview,
    getCrawlerBulkIntervalFailureLabel,
    getCrawlerBulkIntervalSummaryLabel,
    type CrawlerBulkIntervalResponse
  } from "$lib/features/admin/crawlerBulkInterval";
  import {
    CRAWLER_UPDATE_INTERVAL_OPTIONS,
    getCrawlerUpdateIntervalLabel,
    type CrawlerUpdateInterval
  } from "$lib/features/admin/crawlerUpdateInterval";

  type Props = {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    selectionSize: number;
    draft: CrawlerUpdateInterval;
    setDraft: (next: CrawlerUpdateInterval) => void;
    applying: boolean;
    lastResult: CrawlerBulkIntervalResponse | null;
    onApply: () => Promise<void> | void;
    onClose: () => void;
  };

  const {
    open,
    onOpenChange,
    selectionSize,
    draft,
    setDraft,
    applying,
    lastResult,
    onApply,
    onClose
  }: Props = $props();

  const overCap = $derived(selectionSize > CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS);
  const canApply = $derived(
    canSubmitCrawlerBulkIntervalSelection({
      selected_count: selectionSize,
      interval: draft
    })
  );
  const failedPreview = $derived(
    lastResult ? getCrawlerBulkIntervalFailedPreview(lastResult.failed) : null
  );
</script>

<Dialog.Root {open} {onOpenChange}>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title>
        {m.crawler_bulk_interval_dialog_title({ count: String(selectionSize) })}
      </Dialog.Title>
      <Dialog.Description>
        {m.crawler_bulk_interval_dialog_description()}
      </Dialog.Description>
    </Dialog.Header>

    <Field.FieldGroup>
      <Field.Field>
        <Field.FieldLabel for="crawler-bulk-interval-select">
          {m.crawler_bulk_interval_field_label()}
        </Field.FieldLabel>
        <Select.Root
          type="single"
          value={draft}
          onValueChange={(value) => {
            if (value) setDraft(value as CrawlerUpdateInterval);
          }}
          disabled={applying}
        >
          <Select.Trigger
            id="crawler-bulk-interval-select"
            aria-label={m.crawler_bulk_interval_field_label()}
          >
            {getCrawlerUpdateIntervalLabel(draft)}
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

      {#if overCap}
        <Alert.Root variant="destructive">
          <TriangleAlert aria-hidden="true" />
          <Alert.Description>
            {m.crawler_bulk_interval_toolbar_cap_warning({
              limit: String(CRAWLER_BULK_INTERVAL_MAX_WEBSITE_IDS)
            })}
          </Alert.Description>
        </Alert.Root>
      {/if}

      {#if lastResult}
        <div class="border-border rounded-lg border p-3">
          <p class="text-foreground text-sm font-medium">
            {getCrawlerBulkIntervalSummaryLabel(lastResult)}
          </p>
          {#if lastResult.applied.length > 0}
            <p class="text-positive-stronger mt-2 text-xs">
              {m.crawler_bulk_interval_section_applied()}: {lastResult.applied.length}
            </p>
          {/if}
          {#if lastResult.unchanged.length > 0}
            <p class="text-muted-foreground mt-1 text-xs">
              {m.crawler_bulk_interval_section_unchanged()}: {lastResult.unchanged.length}
            </p>
          {/if}
          {#if failedPreview !== null}
            <div class="mt-2">
              <p class="text-destructive text-xs font-medium">
                {m.crawler_bulk_interval_section_failed()}: {lastResult.failed.length}
              </p>
              <ul class="text-muted-foreground mt-1 list-inside list-disc space-y-0.5 text-xs">
                {#each failedPreview.rendered as failedRow (failedRow.website_id)}
                  <li class="font-mono">
                    {failedRow.website_id.slice(0, 8)}…
                    <span class="font-sans">
                      ({getCrawlerBulkIntervalFailureLabel(failedRow.code)})
                    </span>
                  </li>
                {/each}
                {#if failedPreview.remaining > 0}
                  <li class="text-muted-foreground/80">
                    {m.crawler_bulk_interval_more_failures({
                      count: String(failedPreview.remaining)
                    })}
                  </li>
                {/if}
              </ul>
            </div>
          {/if}
        </div>
      {/if}
    </Field.FieldGroup>

    <Dialog.Footer>
      <Button variant="ghost" onclick={onClose} disabled={applying}>
        {lastResult ? m.crawler_bulk_interval_close() : m.crawler_bulk_interval_cancel()}
      </Button>
      {#if !lastResult || lastResult.failed.length > 0}
        <Button variant="default" disabled={!canApply || applying} onclick={() => void onApply()}>
          {applying ? m.crawler_bulk_interval_busy() : m.crawler_bulk_interval_apply()}
        </Button>
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
