<!--
  Lifecycle of one widget: status, save state, why it cannot be activated
  yet, and the activate / pause / archive actions. Activation and archiving
  are for tenant admins; pausing is the kill switch every editor has.
-->
<script lang="ts">
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { blockerLabel } from "./blockers";
  import { widgetErrorMessage } from "./errors";
  import type { WidgetAutosave } from "./widgetAutosave.svelte";

  type Props = {
    autosave: WidgetAutosave;
    isAdmin: boolean;
    onActivate: () => Promise<void>;
    onPause: () => Promise<void>;
    onArchive: () => Promise<void>;
    onReload: () => Promise<void>;
  };

  let { autosave, isAdmin, onActivate, onPause, onArchive, onReload }: Props = $props();

  const widget = $derived(autosave.widget);
  const blockers = $derived(widget.activation_blockers ?? []);
  const canActivate = $derived(isAdmin && blockers.length === 0 && !autosave.hasPending);

  let archiveOpen = $state(false);

  const activate = createAsyncState(async () => {
    try {
      await autosave.flush();
      if (autosave.hasPending) return;
      await onActivate();
    } catch (error) {
      toastError(error, m.widget_admin_could_not_activate());
    }
  });
  const pause = createAsyncState(async () => {
    try {
      await onPause();
    } catch (error) {
      toastError(error, m.widget_admin_could_not_pause());
    }
  });
  const archive = createAsyncState(async () => {
    try {
      await onArchive();
      archiveOpen = false;
    } catch (error) {
      toastError(error, m.widget_admin_could_not_archive());
    }
  });

  const statusLabel = $derived.by(() => {
    switch (widget.status) {
      case "active":
        return m.widget_admin_status_active();
      case "paused":
        return m.widget_admin_status_paused();
      case "archived":
        return m.widget_admin_status_archived();
      default:
        return m.widget_admin_status_draft();
    }
  });

  const saveLabel = $derived.by(() => {
    switch (autosave.status) {
      case "saving":
        return m.widget_admin_saving();
      case "saved":
        return m.widget_admin_saved();
      case "error":
        return m.widget_admin_save_failed();
      case "conflict":
        // A lock published underneath the editor reads differently from
        // another person's edit; both end in a reload.
        return widgetErrorMessage(autosave.error) ?? m.widget_admin_save_conflict();
      default:
        return "";
    }
  });

  const activateTooltip = $derived(
    !isAdmin
      ? m.widget_admin_activate_admin_only()
      : blockers.length > 0
        ? m.widget_admin_activate_blocked()
        : null
  );
</script>

<section
  aria-labelledby="widget-status-title"
  class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4"
>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex flex-wrap items-center gap-3">
      <h2 id="widget-status-title" class="text-base font-semibold">{m.widget_admin_status()}</h2>
      <Badge
        variant={widget.status === "active"
          ? "default"
          : widget.status === "paused"
            ? "destructive"
            : "outline"}>{statusLabel}</Badge
      >
      <span class="text-secondary text-sm" aria-live="polite" aria-atomic="true">
        {saveLabel}
        {#if autosave.status === "error"}
          <Button variant="link" size="sm" onclick={() => autosave.retry()}
            >{m.widget_admin_retry_save()}</Button
          >
        {/if}
        {#if autosave.status === "conflict"}
          <Button
            variant="link"
            size="sm"
            onclick={async () => {
              try {
                await onReload();
              } catch (error) {
                toastError(error);
              }
            }}>{m.widget_admin_reload_discard()}</Button
          >
        {/if}
      </span>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      {#if widget.status === "active"}
        <Button variant="outline" onclick={pause} disabled={pause.isLoading}
          >{m.widget_admin_pause()}</Button
        >
      {:else if widget.status !== "archived"}
        {#if activateTooltip}
          <Tooltip.Root>
            <Tooltip.Trigger>
              {#snippet child({ props })}
                <Button {...props} variant="default" aria-disabled="true" class="opacity-50">
                  {widget.status === "paused" ? m.widget_admin_resume() : m.widget_admin_activate()}
                </Button>
              {/snippet}
            </Tooltip.Trigger>
            <Tooltip.Content>{activateTooltip}</Tooltip.Content>
          </Tooltip.Root>
        {:else}
          <Button
            variant="default"
            onclick={activate}
            disabled={!canActivate || activate.isLoading}
          >
            {widget.status === "paused" ? m.widget_admin_resume() : m.widget_admin_activate()}
          </Button>
        {/if}
      {/if}
      {#if isAdmin && widget.status !== "archived"}
        <Button variant="destructive" onclick={() => (archiveOpen = true)}
          >{m.widget_admin_archive()}</Button
        >
      {/if}
    </div>
  </div>

  {#if blockers.length > 0 && widget.status !== "active"}
    <div class="bg-warning-dimmer text-warning-stronger rounded-lg px-3 py-2 text-sm">
      <p class="font-medium">{m.widget_admin_blockers_title()}</p>
      <ul class="mt-1 list-disc pl-5">
        {#each blockers as blocker (blocker)}
          <li>{blockerLabel(blocker)}</li>
        {/each}
      </ul>
    </div>
  {:else if widget.status === "draft" && !isAdmin}
    <p class="text-secondary text-sm">{m.widget_admin_ready_for_admin()}</p>
  {/if}
</section>

<AlertDialog.Root bind:open={archiveOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.widget_admin_archive_title()}</AlertDialog.Title>
      <AlertDialog.Description>{m.widget_admin_archive_description()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={archive.isLoading}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        class="bg-negative-default text-on-fill"
        disabled={archive.isLoading}
        onclick={(event) => {
          event.preventDefault();
          void archive();
        }}>{m.widget_admin_archive()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
