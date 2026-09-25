<!--
  Confirms activating, resuming, pausing or archiving the reviewed widget.
  Activation is pinned to the revision on screen: when the widget changed in
  the meantime the dialog says so and offers the latest version instead.
-->
<script lang="ts">
  import type { Widget } from "@eneo/eneo-js";
  import { CircleAlert } from "@lucide/svelte";
  import { tick } from "svelte";
  import { invalidate } from "$app/navigation";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { toast } from "$lib/components/toast";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors";
  import { formatList } from "$lib/features/spaces/oversight/format";
  import { widgetErrorCode, widgetErrorMessage } from "$lib/features/widget/admin/errors";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";

  type Props = {
    open?: boolean;
    action: "activate" | "pause" | "archive";
    widget: Widget;
    /** Whether someone in the space asked for activation. */
    requested: boolean;
    /** Where focus goes once the page shows the new state; the opener may be gone. */
    focusAfter: () => HTMLElement | null | undefined;
  };

  let { open = $bindable(false), action, widget, requested, focusAfter }: Props = $props();

  // At 400 % zoom the viewport is about 320 × 256 px: too short for a fixed
  // header and footer around a scrolling body, so the whole dialog scrolls.
  const SHORT_VIEWPORT_CONTENT = "[@media(max-height:30rem)]:overflow-y-auto";
  const SHORT_VIEWPORT_BODY =
    "[@media(max-height:30rem)]:flex-none [@media(max-height:30rem)]:overflow-visible";

  const eneo = getEneo();

  let pending = $state(false);
  let stale = $state(false);
  let failure = $state<string | null>(null);
  let showLatestButton = $state<HTMLElement | null>(null);
  let content = $state<HTMLElement | null>(null);
  // Set when the dialog closes because the page moves on, so focus is placed here, not on the opener.
  let settling = false;
  let closed: () => void = () => {};

  $effect.pre(() => {
    if (!open) return;
    stale = false;
    failure = null;
    settling = false;
  });

  const resume = $derived(widget.status === "paused");

  const copy = $derived.by(() => {
    switch (action) {
      case "activate":
        return {
          title: resume
            ? m.widget_review_resume_title({ name: widget.name })
            : m.widget_review_activate_title({ name: widget.name }),
          description: m.widget_review_activate_body({
            origins: formatList(widget.allowed_origins)
          }),
          confirm: resume ? m.widget_admin_resume() : m.widget_admin_activate(),
          pending: resume ? m.widget_review_resuming() : m.widget_review_activating(),
          done: m.widget_review_activated({ name: widget.name }),
          failed: m.widget_admin_could_not_activate()
        };
      case "pause":
        return {
          title: m.widget_admin_overview_pause_title({ name: widget.name }),
          description: m.widget_admin_overview_pause_description(),
          confirm: m.widget_admin_pause(),
          pending: m.widget_admin_pause(),
          done: m.widget_review_paused({ name: widget.name }),
          failed: m.widget_admin_could_not_pause()
        };
      case "archive":
        return {
          title: m.widget_admin_archive_title(),
          description: m.widget_admin_archive_description(),
          confirm: m.widget_admin_archive(),
          pending: m.widget_admin_archive(),
          done: m.widget_review_archived({ name: widget.name }),
          failed: m.widget_admin_could_not_archive()
        };
    }
  });

  /** Closes the dialog, reloads the review and puts focus on the page's status. */
  async function settle() {
    settling = true;
    const dialogClosed = new Promise<void>((resolve) => (closed = resolve));
    open = false;
    // The close hands focus back through onCloseAutoFocus; if that never
    // comes, the page must not wait for it.
    const timeout = new Promise<void>((resolve) => setTimeout(resolve, 1000));
    await Promise.all([invalidate("admin:widget-review"), Promise.race([dialogClosed, timeout])]);
    await tick();
    focusAfter()?.focus();
  }

  async function confirm() {
    if (pending || stale) return;
    pending = true;
    failure = null;
    try {
      if (action === "activate") {
        await eneo.widgets.activate({ id: widget.id, revision: widget.revision });
      } else if (action === "pause") {
        await eneo.widgets.pause({ id: widget.id });
      } else {
        await eneo.widgets.archive({ id: widget.id });
      }
    } catch (error) {
      if (widgetErrorCode(error) === "widget_revision_conflict") {
        stale = true;
        await tick();
        showLatestButton?.focus();
      } else {
        failure = widgetErrorMessage(error) ?? `${copy.failed}: ${getErrorMessage(error)}`;
      }
      return;
    } finally {
      pending = false;
    }
    toast.success(copy.done);
    await settle();
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
  <AlertDialog.Content
    bind:ref={content}
    class={dialogLayout.content("small", SHORT_VIEWPORT_CONTENT)}
    onOpenAutoFocus={(event) => {
      // Starts on the safe choice, as every confirmation of a consequential action does.
      const cancel = content?.querySelector<HTMLElement>('[data-slot="alert-dialog-cancel"]');
      if (!cancel) return;
      event.preventDefault();
      cancel.focus();
    }}
    onCloseAutoFocus={(event) => {
      if (!settling) return;
      event.preventDefault();
      closed();
    }}
  >
    <AlertDialog.Header class={dialogLayout.header}>
      <AlertDialog.Title class="leading-snug">{copy.title}</AlertDialog.Title>
      <AlertDialog.Description class="text-primary flex flex-col gap-2">
        <span>{copy.description}</span>
        {#if action === "activate" && !requested}
          <span>{m.widget_review_not_requested()}</span>
        {/if}
      </AlertDialog.Description>
    </AlertDialog.Header>

    {#if stale || failure}
      <div class={cn(dialogLayout.body, SHORT_VIEWPORT_BODY)}>
        <div
          role="alert"
          class="bg-negative-dimmer text-negative-stronger flex items-start gap-2 rounded-lg p-3 text-sm"
        >
          <CircleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div class="flex min-w-0 flex-col items-start gap-2">
            <p>{stale ? m.widget_review_stale() : failure}</p>
            {#if stale}
              <Button
                variant="outline"
                class="max-md:min-h-11"
                bind:ref={showLatestButton}
                onclick={settle}>{m.widget_review_show_latest()}</Button
              >
            {/if}
          </div>
        </div>
      </div>
    {/if}

    <AlertDialog.Footer class={dialogLayout.footer}>
      <!-- bits' Cancel ignores `disabled`; the open setter above refuses to close while pending. -->
      <AlertDialog.Cancel
        class={cn("max-md:min-h-11", pending && "pointer-events-none opacity-50")}
        aria-disabled={pending}>{m.cancel()}</AlertDialog.Cancel
      >
      {#if !stale}
        <!-- aria-disabled, not disabled, while pending: a focused button that becomes disabled drops focus. -->
        <Button
          class={cn(
            "max-md:min-h-11",
            action === "archive" && "bg-negative-default text-on-fill hover:bg-negative-default/90",
            pending && "pointer-events-none opacity-50"
          )}
          aria-disabled={pending}
          aria-busy={pending}
          onclick={confirm}
        >
          {pending ? copy.pending : copy.confirm}
        </Button>
      {/if}
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
