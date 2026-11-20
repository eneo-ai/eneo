<!--
  Lifecycle of one widget: status, save state, why it cannot be activated
  yet (or, once active, what keeps it from serving properly), and the
  activate / pause / archive actions. Activation and archiving
  are for tenant admins; pausing is the kill switch every
  editor has.
-->
<script lang="ts">
  import { tick } from "svelte";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { blockerLabel } from "./blockers";
  import { toastWidgetError, widgetErrorMessage } from "./errors";
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
  const refusals = $derived([...new Set(Object.values(autosave.refusals))]);
  const canActivate = $derived(isAdmin && blockers.length === 0 && !autosave.hasPending);
  let archiveOpen = $state(false);
  let heading = $state<HTMLElement>();
  const pressed = () => {
    const active = document.activeElement;
    return active instanceof HTMLElement && active !== document.body ? active : null;
  };
  const usable = (element: HTMLElement | null): element is HTMLElement =>
    !!element?.isConnected && !element.matches(":disabled");

  async function refocus(
    button: HTMLElement | null,
    fallback: () => HTMLElement | null | undefined
  ) {
    await tick();
    const active = document.activeElement;
    // Focus the user has moved on stays where it is. Focus still on a button
    // the action left disabled is not: browsers drop it, or strand it there.
    if (active && active !== document.body && !active.matches(":disabled")) return;
    (usable(button) ? button : fallback())?.focus();
  }

  const activate = createAsyncState(async () => {
    try {
      await autosave.flush();
      if (autosave.hasPending) return;
      await onActivate();
    } catch (error) {
      toastWidgetError(error, m.widget_admin_could_not_activate());
    }
  });
  async function startActivation() {
    const button = pressed();
    await activate();
    await refocus(button, () => heading);
  }
  const pause = createAsyncState(async () => {
    try {
      await onPause();
    } catch (error) {
      toastError(error, m.widget_admin_could_not_pause());
    }
  });
  async function startPause() {
    const button = pressed();
    await pause();
    await refocus(button, () => heading);
  }
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
      case "refused":
        return m.widget_admin_save_refused();
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
  // The tooltip never opens on touch, so the reason is also written out below.
  const adminOnlyNote = $derived(
    isAdmin || blockers.length > 0
      ? null
      : widget.status === "draft"
        ? m.widget_admin_ready_for_admin()
        : widget.status === "paused"
          ? m.widget_admin_resume_admin_only()
          : null
  );
  const externalToolsNote = $derived(
    isAdmin && blockers.length === 0 && (widget.status === "draft" || widget.status === "paused")
      ? m.widget_admin_external_tools_note()
      : null
  );
  const activateReasonId = $derived(
    blockers.length > 0
      ? "widget-status-blockers"
      : adminOnlyNote
        ? "widget-status-admin-only"
        : externalToolsNote
          ? "widget-status-external-tools"
          : null
  );
</script>

<section
  aria-labelledby="widget-status-title"
  class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4"
>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <div class="flex flex-wrap items-center gap-3">
      <h2
        id="widget-status-title"
        tabindex="-1"
        bind:this={heading}
        class="text-base font-semibold"
      >
        {m.widget_admin_status()}
      </h2>
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
        <Button variant="outline" onclick={startPause} disabled={pause.isLoading}
          >{m.widget_admin_pause()}</Button
        >
      {:else if widget.status !== "archived"}
        {#if activateTooltip}
          <Tooltip.Root>
            <Tooltip.Trigger>
              {#snippet child({ props })}
                <Button
                  {...props}
                  variant="default"
                  aria-disabled="true"
                  aria-describedby={[props["aria-describedby"], activateReasonId]
                    .filter(Boolean)
                    .join(" ") || undefined}
                  class="opacity-50"
                >
                  {widget.status === "paused" ? m.widget_admin_resume() : m.widget_admin_activate()}
                </Button>
              {/snippet}
            </Tooltip.Trigger>
            <Tooltip.Content>{activateTooltip}</Tooltip.Content>
          </Tooltip.Root>
        {:else}
          <Button
            variant="default"
            onclick={startActivation}
            disabled={!canActivate || activate.isLoading}
            aria-describedby={activateReasonId ?? undefined}
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

  {#if refusals.length > 0}
    <div class="bg-negative-dimmer text-negative-stronger rounded-lg px-3 py-2 text-sm">
      <p class="font-medium">{m.widget_admin_refusals_title()}</p>
      <ul class="mt-1 list-disc pl-5">
        {#each refusals as message (message)}
          <li>{message}</li>
        {/each}
      </ul>
    </div>
  {/if}
  {#if blockers.length > 0}
    <div
      id="widget-status-blockers"
      class="bg-warning-dimmer text-warning-stronger rounded-lg px-3 py-2 text-sm"
    >
      <p class="font-medium">
        {widget.status === "active"
          ? m.widget_admin_active_issues_title()
          : m.widget_admin_blockers_title()}
      </p>
      <ul class="mt-1 list-disc pl-5">
        {#each blockers as blocker (blocker)}
          <li>{blockerLabel(blocker)}</li>
        {/each}
      </ul>
    </div>
  {:else if adminOnlyNote}
    <p id="widget-status-admin-only" class="text-secondary text-sm">{adminOnlyNote}</p>
  {:else if externalToolsNote}
    <p id="widget-status-external-tools" class="text-secondary text-sm">{externalToolsNote}</p>
  {/if}
</section>

<AlertDialog.Root bind:open={archiveOpen}>
  <AlertDialog.Content escapeKeydownBehavior={archive.isLoading ? "ignore" : "close"}>
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
