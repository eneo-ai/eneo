<!--
  Confirms activating, resuming, pausing or archiving the reviewed widget.
  Activation is pinned to the revision on screen: when the widget changed in
  the meantime the dialog says so and offers the latest version instead.
-->
<script lang="ts">
  import type { Widget } from "@eneo/eneo-js";
  import { tick } from "svelte";
  import { invalidate } from "$app/navigation";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import InlineError from "$lib/components/InlineError.svelte";
  import { toast } from "$lib/components/toast";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessageWithContext } from "$lib/core/errors";
  import { formatList } from "$lib/core/formatting/formatList";
  import { widgetErrorCode, widgetErrorMessage } from "$lib/features/widget/admin/errors";
  import { m } from "$lib/paraglide/messages";

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

  const eneo = getEneo();

  let stale = $state(false);
  let failure = $state<string | null>(null);
  let showLatestButton = $state<HTMLElement | null>(null);

  $effect.pre(() => {
    if (!open) return;
    stale = false;
    failure = null;
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
          pending: m.widget_review_pausing(),
          done: m.widget_review_paused({ name: widget.name }),
          failed: m.widget_admin_could_not_pause()
        };
      case "archive":
        return {
          title: m.widget_admin_archive_title(),
          description: m.widget_admin_archive_description(),
          confirm: m.widget_admin_archive(),
          pending: m.widget_review_archiving(),
          done: m.widget_review_archived({ name: widget.name }),
          failed: m.widget_admin_could_not_archive()
        };
    }
  });

  async function confirm() {
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
        failure = widgetErrorMessage(error) ?? getErrorMessageWithContext(error, copy.failed);
      }
      throw error;
    }
    toast.success(copy.done);
  }
</script>

{#snippet body()}
  <span class="text-primary flex flex-col gap-2">
    <span>{copy.description}</span>
    {#if action === "activate" && !requested}
      <span>{m.widget_review_not_requested()}</span>
    {/if}
  </span>
{/snippet}

{#snippet problem({ settle }: { settle: () => Promise<void> })}
  <InlineError>
    <p>{stale ? m.widget_review_stale() : failure}</p>
    {#if stale}
      <Button variant="outline" class="max-md:min-h-11" bind:ref={showLatestButton} onclick={settle}
        >{m.widget_review_show_latest()}</Button
      >
    {/if}
  </InlineError>
{/snippet}

<ConfirmDialog
  bind:open
  title={copy.title}
  description={body}
  confirmLabel={copy.confirm}
  pendingLabel={copy.pending}
  variant={action === "archive" ? "destructive" : "default"}
  errorDisplay="none"
  confirmHidden={stale}
  alert={stale || failure ? problem : undefined}
  onConfirm={confirm}
  reload={() => invalidate("admin:widget-review")}
  {focusAfter}
/>
