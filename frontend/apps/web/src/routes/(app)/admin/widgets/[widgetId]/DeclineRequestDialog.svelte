<!--
  Sends a pending activation request back to the space's editors with what
  needs to change. The API calls this declining; the editors see the message
  in the widget editor and can ask again.
-->
<script lang="ts">
  import type { Widget } from "@eneo/eneo-js";
  import { tick } from "svelte";
  import { invalidate } from "$app/navigation";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import InlineError from "$lib/components/InlineError.svelte";
  import { settleDialog } from "$lib/components/settleDialog";
  import { toast } from "$lib/components/toast";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessageWithContext } from "$lib/core/errors";
  import { reasonError } from "$lib/features/spaces/oversight/reason";
  import ReasonField from "$lib/features/spaces/oversight/ReasonField.svelte";
  import { widgetErrorCode, widgetErrorMessage } from "$lib/features/widget/admin/errors";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";

  type Props = {
    open?: boolean;
    widget: Widget;
    /** Where focus goes once the page shows the new state; the opener is gone by then. */
    focusAfter: () => HTMLElement | null | undefined;
  };

  let { open = $bindable(false), widget, focusAfter }: Props = $props();

  const eneo = getEneo();
  const uid = $props.id();

  let reason = $state("");
  // Checked from the first submit on, so the message goes away once the reason is long enough.
  let attempted = $state(false);
  const reasonMessage = $derived(attempted ? reasonError(reason) : null);
  let serverError = $state<string | null>(null);
  let pending = $state(false);
  let reasonInput = $state<HTMLTextAreaElement | null>(null);

  const settler = settleDialog({
    close: () => (open = false),
    reload: () => invalidate("admin:widget-review"),
    focusAfter: () => focusAfter()
  });

  $effect.pre(() => {
    if (!open) return;
    reason = "";
    attempted = false;
    serverError = null;
    settler.reset();
  });

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (pending) return;
    serverError = null;
    attempted = true;
    if (reasonError(reason)) {
      await tick();
      reasonInput?.focus();
      return;
    }

    pending = true;
    try {
      await eneo.widgets.declineActivationRequest({ id: widget.id, reason });
    } catch (error) {
      if (widgetErrorCode(error) === "widget_activation_request_missing") {
        // Withdrawn or settled meanwhile: nothing is left to send back.
        toast.error(m.widget_request_error_missing());
        pending = false;
        await settler.settle();
        return;
      }
      serverError =
        widgetErrorMessage(error) ??
        getErrorMessageWithContext(error, m.widget_review_return_failed());
      return;
    } finally {
      pending = false;
    }
    toast.success(m.widget_review_returned_toast());
    await settler.settle();
  }
</script>

<Dialog.Root
  bind:open={
    () => open,
    (value) => {
      if (!pending) open = value;
    }
  }
>
  <Dialog.Content
    class={dialogLayout.content("medium")}
    closeLabel={m.close()}
    onOpenAutoFocus={(event) => {
      event.preventDefault();
      reasonInput?.focus();
    }}
    onCloseAutoFocus={settler.onCloseAutoFocus}
  >
    <form class="contents" novalidate onsubmit={submit}>
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title class="leading-snug">{m.widget_review_return_title()}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <!-- In the scrolling body, so a phone keeps room for the form. -->
        <Dialog.Description class="text-primary text-sm">
          {widget.status === "paused"
            ? m.widget_review_return_body_paused()
            : m.widget_review_return_body_draft()}
        </Dialog.Description>

        <ReasonField
          id={`${uid}-reason`}
          label={m.widget_review_return_label()}
          help={m.widget_review_return_help()}
          bind:value={reason}
          bind:ref={reasonInput}
          error={reasonMessage}
          rows={4}
        />

        {#if serverError}
          <InlineError message={serverError} />
        {/if}
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close
          type="button"
          class={cn(
            buttonVariants({ variant: "outline" }),
            "max-md:min-h-11",
            pending && "pointer-events-none opacity-50"
          )}
          aria-disabled={pending}
        >
          {m.cancel()}
        </Dialog.Close>
        <!-- aria-disabled, not disabled: a focused button that becomes disabled drops focus. -->
        <Button
          type="submit"
          class={["max-md:min-h-11", pending && "pointer-events-none opacity-50"]}
          aria-disabled={pending}
          aria-busy={pending}
        >
          {pending ? m.widget_request_pending() : m.widget_review_return_confirm()}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
