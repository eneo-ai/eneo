<!--
  Lifecycle of one widget: status, save state, why it cannot be activated
  yet (or, once active, what keeps it from serving properly), and the
  activate / pause / archive actions. Activation and archiving are for tenant
  admins; pausing is the kill switch every editor has.
-->
<script lang="ts">
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
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
    /**
     * `externalToolsAcknowledged` is true only when the admin has just
     * confirmed, in the dialog here, that anonymous visitors can make the
     * assistant call its MCP servers outside Eneo.
     */
    onActivate: (options: { externalToolsAcknowledged: boolean }) => Promise<void>;
    onPause: () => Promise<void>;
    onArchive: () => Promise<void>;
    onReload: () => Promise<void>;
  };

  let { autosave, isAdmin, onActivate, onPause, onArchive, onReload }: Props = $props();

  const widget = $derived(autosave.widget);
  const blockers = $derived(widget.activation_blockers ?? []);
  const refusals = $derived([...new Set(Object.values(autosave.refusals))]);
  const canActivate = $derived(isAdmin && blockers.length === 0 && !autosave.hasPending);
  // The assistant's MCP servers outside Eneo, as the backend lists them, and
  // whether the stored acknowledgement covers them. Activation stops at a
  // dialog until the admin has read the list and said yes.
  const externalTools = $derived(widget.external_tools ?? []);
  const needsAcknowledgement = $derived(
    externalTools.length > 0 && !(widget.external_tools_acknowledged ?? true)
  );

  let archiveOpen = $state(false);
  let consentOpen = $state(false);
  let acknowledged = $state(false);

  const activate = createAsyncState(async () => {
    try {
      await autosave.flush();
      if (autosave.hasPending) return;
      if (needsAcknowledgement) {
        acknowledged = false;
        consentOpen = true;
        return;
      }
      await onActivate({ externalToolsAcknowledged: false });
    } catch (error) {
      toastWidgetError(error, m.widget_admin_could_not_activate());
    }
  });
  const activateAcknowledged = createAsyncState(async () => {
    try {
      await onActivate({ externalToolsAcknowledged: true });
      consentOpen = false;
    } catch (error) {
      toastWidgetError(error, m.widget_admin_could_not_activate());
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
  // An admin about to activate is told up front that a dialog follows.
  const externalToolsNote = $derived(
    isAdmin && blockers.length === 0 && widget.status !== "active" && needsAcknowledgement
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
    <!-- An active widget with blockers is live but not serving as configured
         (an unpublished assistant, no allowed website, no AI disclosure). -->
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

<AlertDialog.Root bind:open={consentOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.widget_admin_external_tools_title()}</AlertDialog.Title>
      <AlertDialog.Description
        >{m.widget_admin_external_tools_description()}</AlertDialog.Description
      >
    </AlertDialog.Header>
    <ul class="flex flex-col gap-2 text-sm" aria-label={m.widget_admin_external_tools_servers()}>
      {#each externalTools as server (server.id)}
        <li class="border-default rounded-md border px-3 py-2">
          <p class="font-medium">{server.name}</p>
          <p class="text-secondary">
            {server.tools.length > 0
              ? m.widget_admin_external_tools_tools({ tools: server.tools.join(", ") })
              : m.widget_admin_external_tools_no_tools()}
          </p>
        </li>
      {/each}
    </ul>
    <div class="flex items-start gap-3">
      <Checkbox
        id="widget-external-tools-ack"
        class="mt-0.5"
        bind:checked={acknowledged}
        aria-describedby="widget-external-tools-ack-help"
      />
      <div class="flex flex-col gap-1">
        <Label for="widget-external-tools-ack" class="leading-snug"
          >{m.widget_admin_external_tools_acknowledge()}</Label
        >
        <p id="widget-external-tools-ack-help" class="text-secondary text-sm">
          {m.widget_admin_external_tools_acknowledge_help()}
        </p>
      </div>
    </div>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={activateAcknowledged.isLoading}>{m.cancel()}</AlertDialog.Cancel
      >
      <AlertDialog.Action
        disabled={!acknowledged || activateAcknowledged.isLoading}
        onclick={(event) => {
          event.preventDefault();
          void activateAcknowledged();
        }}
      >
        {widget.status === "paused" ? m.widget_admin_resume() : m.widget_admin_activate()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

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
