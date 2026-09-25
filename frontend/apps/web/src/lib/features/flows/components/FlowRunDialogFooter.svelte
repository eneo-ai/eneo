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
    liveTextFinishing = false,
    canGoPrevious = true,
    nextDisabledReason,
    reasonId,
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
    // A recording's final text is still coming, and the run waits for it.
    liveTextFinishing?: boolean;
    // False while a step records: going back would drop its recording.
    canGoPrevious?: boolean;
    nextDisabledReason: string | undefined;
    // The id of the line that says why navigation is disabled.
    reasonId: string;
    labels: FlowRunDialogLabels;
    onCancelClose: () => void;
    onGoNext: () => void;
    onGoPrevious: () => void;
    onTriggerRun: () => void;
    onApplyLastInput: () => void;
    onRequestClose: () => void;
  } = $props();

  // Only when the final text is all the run waits for.
  const awaitsLiveText = $derived(liveTextFinishing && canSubmitRun);
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
            id={reasonId}
            class="text-secondary text-sm leading-relaxed sm:text-right"
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
        <!-- DOM order is the desktop reading order (Avbryt, Föregående, then the
             forward action), so Tab moves the way the eye does; the order
             classes only restack the column on narrow screens. -->
        {#if isDirty && !isSubmitting}
          <Button
            variant="outline"
            onclick={onRequestClose}
            class="order-3 w-full sm:order-none sm:w-auto"
          >
            {m.cancel()}
          </Button>
        {:else}
          <Dialog.Close>
            {#snippet child({ props })}
              <Button variant="outline" class="order-3 w-full sm:order-none sm:w-auto" {...props}>
                {m.cancel()}
              </Button>
            {/snippet}
          </Dialog.Close>
        {/if}

        {#if showPrevious}
          <Button
            variant="outline"
            onclick={onGoPrevious}
            disabled={!canGoPrevious}
            title={canGoPrevious ? undefined : nextDisabledReason}
            aria-describedby={canGoPrevious ? undefined : reasonId}
            class="order-2 w-full sm:order-none sm:w-auto"
          >
            {labels.previous}
          </Button>
        {/if}

        {#if isReviewPage}
          <!-- While the final text comes the button is not disabled, so focus
               stays on it; a press does nothing. -->
          <Button
            onclick={onTriggerRun}
            disabled={!canSubmitRun}
            aria-disabled={awaitsLiveText || undefined}
            class="order-1 w-full min-w-[8rem] sm:order-none sm:w-auto"
          >
            {#if isSubmitting || awaitsLiveText}
              <IconLoadingSpinner data-icon="inline-start" class="animate-spin" />
            {/if}
            {awaitsLiveText ? m.flow_run_finishing_live_text() : m.flow_run_trigger_confirm()}
          </Button>
        {:else}
          <Button
            onclick={onGoNext}
            disabled={!canGoNext}
            title={nextDisabledReason}
            aria-describedby={!canGoNext && nextDisabledReason ? reasonId : undefined}
            class="order-1 w-full min-w-[7rem] sm:order-none sm:w-auto"
          >
            {labels.next}
          </Button>
        {/if}
      </div>
    </div>
  {/if}
</footer>
