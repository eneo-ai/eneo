<script lang="ts">
  import type { Snippet } from "svelte";
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button, type ButtonVariant } from "$lib/components/ui/button/index.js";
  import { dialogLayout, type DialogWidth } from "$lib/components/dialogLayout.js";
  import { getErrorMessage, toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";

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
    /** Where a failure is reported: a toast, or a message inside the dialog. */
    errorDisplay?: "toast" | "inline";
    /** Keeps the confirm button disabled, e.g. while prerequisites load. */
    confirmDisabled?: boolean;
    /** The dialog closes when this resolves; when it throws, it stays open and shows the error. */
    onConfirm: () => unknown;
    /** Renders the element that opens the dialog; spread `props` onto it. */
    trigger?: Snippet<[{ props: Record<string, unknown> }]>;
    /** Extra content between the description and the buttons. */
    children?: Snippet;
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
    onConfirm,
    trigger,
    children
  }: Props = $props();

  let pending = $state(false);
  let inlineError = $state<string | null>(null);

  $effect(() => {
    if (open) inlineError = null;
  });

  async function confirm() {
    if (pending || confirmDisabled) return;
    pending = true;
    inlineError = null;
    try {
      await onConfirm();
      open = false;
    } catch (error) {
      if (errorDisplay === "inline") {
        const message = getErrorMessage(error);
        inlineError = errorContext ? `${errorContext}: ${message}` : message;
      } else {
        toastError(error, errorContext);
      }
    } finally {
      pending = false;
    }
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

  <AlertDialog.Content class={dialogLayout.content(width)}>
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title>{title}</AlertDialog.Title>
      {#if typeof description === "string"}
        <AlertDialog.Description>{description}</AlertDialog.Description>
      {:else if description}
        <AlertDialog.Description>{@render description()}</AlertDialog.Description>
      {/if}
    </AlertDialog.Header>

    {#if children || inlineError}
      <div class={dialogLayout.body}>
        {@render children?.()}
        {#if inlineError}
          <Alert.Root variant="destructive">
            <CircleAlert />
            <Alert.Description>{inlineError}</Alert.Description>
          </Alert.Root>
        {/if}
      </div>
    {/if}

    <AlertDialog.Footer class={dialogLayout.footer}>
      <!-- bits' Cancel ignores `disabled`; the open setter above already refuses to close while pending. -->
      <AlertDialog.Cancel
        aria-disabled={pending}
        class={pending ? "pointer-events-none opacity-50" : undefined}
        >{cancelLabel ?? m.cancel()}</AlertDialog.Cancel
      >
      <!-- aria-disabled, not disabled, while pending: a focused button that becomes disabled drops
           focus out of the dialog, and the dialog stays open when the action fails. -->
      <Button
        {variant}
        disabled={confirmDisabled}
        aria-disabled={pending}
        aria-busy={pending}
        class={pending ? "pointer-events-none opacity-50" : undefined}
        onclick={confirm}
      >
        {pending && pendingLabel ? pendingLabel : confirmLabel}
      </Button>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
