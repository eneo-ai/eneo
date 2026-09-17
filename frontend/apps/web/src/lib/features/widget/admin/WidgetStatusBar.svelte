<!--
  Lifecycle of one widget: status, why it cannot be activated yet, and the
  activate / pause / archive actions. Activation and archiving are for
  tenant admins; pausing is the kill switch every editor has.
-->
<script lang="ts">
  import { Button, Dialog, Tooltip } from "@eneo/ui";
  import { writable } from "svelte/store";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { blockerLabel } from "./blockers";
  import type { WidgetAutosave } from "./widgetAutosave.svelte";

  type Props = {
    autosave: WidgetAutosave;
    isAdmin: boolean;
    onActivate: () => Promise<void>;
    onPause: () => Promise<void>;
    onArchive: () => Promise<void>;
  };

  let { autosave, isAdmin, onActivate, onPause, onArchive }: Props = $props();

  const widget = $derived(autosave.widget);
  const blockers = $derived(widget.activation_blockers ?? []);
  const canActivate = $derived(isAdmin && blockers.length === 0 && !autosave.hasPending);

  const showArchive = writable(false);

  const activate = createAsyncState(async () => {
    try {
      await autosave.flush();
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
      $showArchive = false;
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
      default:
        return "";
    }
  });

  const activateTooltip = $derived(
    !isAdmin
      ? m.widget_admin_activate_admin_only()
      : blockers.length > 0
        ? m.widget_admin_activate_blocked()
        : undefined
  );
</script>

<section
  aria-labelledby="widget-status-title"
  class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4"
>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex items-center gap-3">
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
          <button type="button" class="ml-1 underline" onclick={() => autosave.retry()}
            >{m.widget_admin_retry_save()}</button
          >
        {/if}
      </span>
    </div>

    <div class="flex flex-wrap items-center gap-2">
      {#if widget.status === "active"}
        <Button variant="warning-outlined" onclick={pause} disabled={pause.isLoading}
          >{m.widget_admin_pause()}</Button
        >
      {:else if widget.status !== "archived"}
        <Tooltip text={activateTooltip}>
          <Button
            variant="primary"
            onclick={activate}
            disabled={!canActivate || activate.isLoading}
            aria-disabled={!canActivate}
          >
            {widget.status === "paused" ? m.widget_admin_resume() : m.widget_admin_activate()}
          </Button>
        </Tooltip>
      {/if}
      {#if isAdmin && widget.status !== "archived"}
        <Button variant="destructive" onclick={() => ($showArchive = true)}
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

<Dialog.Root openController={showArchive}>
  <Dialog.Content>
    <Dialog.Title>{m.widget_admin_archive_title()}</Dialog.Title>
    <Dialog.Description>{m.widget_admin_archive_description()}</Dialog.Description>
    <Dialog.Controls>
      <Button onclick={() => ($showArchive = false)}>{m.cancel()}</Button>
      <Button variant="destructive" onclick={archive} disabled={archive.isLoading}
        >{m.widget_admin_archive()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
