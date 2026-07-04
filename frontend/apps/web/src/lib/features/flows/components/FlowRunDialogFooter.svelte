<script lang="ts">
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";
  import type { FlowRunDialogLabels } from "./flowRunDialogLabels";

  let {
    showCloseConfirmation,
    isDirty,
    isSubmitting,
    canGoNext,
    canSubmitRun,
    isReviewPage,
    showReuseLastInput,
    showPrevious,
    nextDisabledReason,
    labels,
    onCancelClose,
    onGoNext,
    onGoPrevious,
    onTriggerRun,
    onApplyLastInput,
    onRequestClose
  }: {
    showCloseConfirmation: boolean;
    isDirty: boolean;
    isSubmitting: boolean;
    canGoNext: boolean;
    canSubmitRun: boolean;
    isReviewPage: boolean;
    showReuseLastInput: boolean;
    showPrevious: boolean;
    nextDisabledReason: string | undefined;
    labels: FlowRunDialogLabels;
    onCancelClose: () => void;
    onGoNext: () => void;
    onGoPrevious: () => void;
    onTriggerRun: () => void;
    onApplyLastInput: () => void;
    onRequestClose: () => void;
  } = $props();
</script>

<footer
  class="border-default shrink-0 border-t px-4 py-3 sm:px-6 sm:py-3.5 lg:px-8 {showCloseConfirmation
    ? 'bg-warning-dimmer/25'
    : ''}"
>
  {#if showCloseConfirmation}
    <div
      class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
      role="alertdialog"
      aria-label={labels.closeConfirmTitle}
      aria-describedby="close-confirm-desc"
    >
      <div class="min-w-0">
        <p class="text-primary text-sm font-medium">{labels.closeConfirmTitle}</p>
        <p id="close-confirm-desc" class="text-muted mt-0.5 text-sm">
          {labels.closeConfirmMessage}
        </p>
      </div>
      <div class="flex shrink-0 gap-2">
        <Button variant="outline" size="sm" onclick={onCancelClose}>
          {labels.closeConfirmKeep}
        </Button>
        <Dialog.Close>
          {#snippet child({ props })}
            <Button variant="destructive" size="sm" {...props}>
              {labels.closeConfirmDiscard}
            </Button>
          {/snippet}
        </Dialog.Close>
      </div>
    </div>
  {:else}
    <div class="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
      <div class="order-2 flex gap-2 sm:order-1">
        {#if showReuseLastInput}
          <Button variant="outline" onclick={onApplyLastInput} class="w-full sm:w-auto">
            {m.flow_run_reuse_last_input()}
          </Button>
        {/if}
      </div>

      <div class="order-1 flex-grow sm:order-2">
        {#if !isReviewPage && !canGoNext && nextDisabledReason}
          <p
            class="text-muted text-sm leading-relaxed sm:text-right"
            role="status"
            aria-live="polite"
          >
            {nextDisabledReason}
          </p>
        {/if}
      </div>

      <div
        class="order-2 flex w-full flex-col gap-2 sm:order-3 sm:w-auto sm:flex-row sm:items-center"
      >
        {#if isReviewPage}
          <Button
            onclick={onTriggerRun}
            disabled={!canSubmitRun}
            class="order-1 w-full min-w-[8rem] sm:order-3 sm:w-auto"
          >
            {#if isSubmitting}
              <IconLoadingSpinner data-icon="inline-start" class="animate-spin" />
            {/if}
            {m.flow_run_trigger_confirm()}
          </Button>
        {:else}
          <Button
            onclick={onGoNext}
            disabled={!canGoNext}
            title={nextDisabledReason}
            class="order-1 w-full min-w-[7rem] sm:order-3 sm:w-auto"
          >
            {labels.next}
          </Button>
        {/if}

        {#if isDirty && !isSubmitting}
          <Button
            variant="outline"
            onclick={onRequestClose}
            class="order-3 w-full sm:order-2 sm:w-auto"
          >
            {m.cancel()}
          </Button>
        {:else}
          <Dialog.Close>
            {#snippet child({ props })}
              <Button variant="outline" class="order-3 w-full sm:order-2 sm:w-auto" {...props}>
                {m.cancel()}
              </Button>
            {/snippet}
          </Dialog.Close>
        {/if}

        {#if showPrevious}
          <Button
            variant="outline"
            onclick={onGoPrevious}
            class="order-2 w-full sm:order-1 sm:w-auto"
          >
            {labels.previous}
          </Button>
        {/if}
      </div>
    </div>
  {/if}
</footer>
