<script lang="ts">
  import type { Snippet } from "svelte";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button, type ButtonVariant } from "$lib/components/ui/button/index.js";
  import { dialogLayout, type DialogWidth } from "$lib/components/dialogLayout.js";
  import InlineError from "$lib/components/InlineError.svelte";
  import { settleDialog } from "$lib/components/settleDialog";
  import { getErrorMessageWithContext, toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";

  type Props = {
    open?: boolean;
    title: string;
    description?: string | Snippet;
    confirmLabel: string;
    /** Shown on the confirm button while `onConfirm` runs. */
    pendingLabel?: string;
    cancelLabel?: string;
    variant?: ButtonVariant;
    width?: DialogWidth;
    /** Prefix for the error message, e.g. `m.could_not_delete_service()`. */
    errorContext?: string;
    /**
     * Where a failure is reported: a toast, a message inside the dialog, or nowhere because
     * `onConfirm` reports it itself in `alert`; a throw then only keeps the dialog open.
     */
    errorDisplay?: "toast" | "inline" | "none";
    /** Keeps the confirm button disabled, e.g. while prerequisites load. */
    confirmDisabled?: boolean;
    /** Leaves only Cancel, e.g. when `alert` offers the way forward instead. */
    confirmHidden?: boolean;
    /** The dialog closes when this resolves; when it throws, it stays open and shows the error. */
    onConfirm: () => unknown;
    /**
     * Where focus goes after the action, once `reload` has run, instead of back to the opener,
     * which the action may have removed.
     */
    focusAfter?: () => HTMLElement | null | undefined;
    /** Loads the page's new state while the dialog closes, e.g. `invalidate(...)`. */
    reload?: () => Promise<unknown>;
    /** Renders the element that opens the dialog; spread `props` onto it. */
    trigger?: Snippet<[{ props: Record<string, unknown> }]>;
    /** Extra content between the description and the buttons. */
    children?: Snippet;
    /**
     * A problem shown above the buttons. `settle` closes the dialog, reloads and moves focus as a
     * confirmed action does, for a way out such as showing the latest version.
     */
    alert?: Snippet<[{ settle: () => Promise<void> }]>;
  };

  let {
    open = $bindable(false),
    title,
    description,
    confirmLabel,
    pendingLabel,
    cancelLabel,
    variant = "destructive",
    width = "small",
    errorContext,
    errorDisplay = "toast",
    confirmDisabled = false,
    confirmHidden = false,
    onConfirm,
    focusAfter,
    reload,
    trigger,
    children,
    alert
  }: Props = $props();

  let pending = $state(false);
  let inlineError = $state<string | null>(null);
  let cancelButton = $state<HTMLElement | null>(null);

  const settler = settleDialog({
    close: () => (open = false),
    reload: async () => await reload?.(),
    focusAfter: () => focusAfter?.()
  });

  $effect(() => {
    if (!open) return;
    inlineError = null;
    settler.reset();
  });

  async function confirm() {
    if (pending || confirmDisabled || confirmHidden) return;
    pending = true;
    inlineError = null;
    try {
      await onConfirm();
    } catch (error) {
      if (errorDisplay === "inline") {
        inlineError = getErrorMessageWithContext(error, errorContext);
      } else if (errorDisplay === "toast") {
        toastError(error, errorContext);
      }
      return;
    } finally {
      pending = false;
    }
    if (focusAfter) await settler.settle();
    else open = false;
  }
</script>

<AlertDialog.Root
  bind:open={
    () => open,
    (value) => {
      if (!pending) open = value;
    }
  }
>
  {#if trigger}
    <AlertDialog.Trigger>
      {#snippet child({ props })}
        {@render trigger({ props })}
      {/snippet}
    </AlertDialog.Trigger>
  {/if}

  <AlertDialog.Content
    class={dialogLayout.content(width)}
    onOpenAutoFocus={(event) => {
      // The least destructive choice first, so a stray Enter confirms nothing.
      if (!cancelButton) return;
      event.preventDefault();
      cancelButton.focus();
    }}
    onCloseAutoFocus={settler.onCloseAutoFocus}
  >
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title>{title}</AlertDialog.Title>
      {#if typeof description === "string"}
        <AlertDialog.Description>{description}</AlertDialog.Description>
      {:else if description}
        <AlertDialog.Description>{@render description()}</AlertDialog.Description>
      {/if}
    </AlertDialog.Header>

    {#if children || alert || inlineError}
      <div class={dialogLayout.body}>
        {@render children?.()}
        {@render alert?.({ settle: settler.settle })}
        {#if inlineError}
          <InlineError message={inlineError} />
        {/if}
      </div>
    {/if}

    <AlertDialog.Footer class={dialogLayout.footer}>
      <!-- bits' Cancel ignores `disabled`; the open setter above already refuses to close while pending. -->
      <AlertDialog.Cancel
        bind:ref={cancelButton}
        aria-disabled={pending}
        class={cn("max-md:min-h-11", pending && "pointer-events-none opacity-50")}
        >{cancelLabel ?? m.cancel()}</AlertDialog.Cancel
      >
      {#if !confirmHidden}
        <!-- aria-disabled, not disabled, while pending: a focused button that becomes disabled drops
             focus out of the dialog, and the dialog stays open when the action fails. -->
        <Button
          {variant}
          disabled={confirmDisabled}
          aria-disabled={pending}
          aria-busy={pending}
          class={cn("max-md:min-h-11", pending && "pointer-events-none opacity-50")}
          onclick={confirm}
        >
          {pending && pendingLabel ? pendingLabel : confirmLabel}
        </Button>
      {/if}
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
