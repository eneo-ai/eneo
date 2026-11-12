<!--
  Lifecycle of one widget: status, save state, why it cannot be activated
  yet (or, once active, what keeps it from serving properly), and the
  activate / pause / archive actions. Activation, archiving and acknowledging
  tools outside Eneo are for tenant admins; pausing is the kill switch every
  editor has.
-->
<script lang="ts">
  import type { Widget } from "@eneo/eneo-js";
  import { tick } from "svelte";
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
  import { currentExternalTools, toastWidgetError, widgetErrorMessage } from "./errors";
  import type { WidgetAutosave } from "./widgetAutosave.svelte";

  type Props = {
    autosave: WidgetAutosave;
    isAdmin: boolean;
    onActivate: () => Promise<void>;
    /** Acknowledges exactly the servers and tools the admin was shown. */
    onAcknowledgeExternalTools: (servers: Widget["external_tools"]) => Promise<void>;
    onPause: () => Promise<void>;
    onArchive: () => Promise<void>;
    onReload: () => Promise<void>;
  };

  let {
    autosave,
    isAdmin,
    onActivate,
    onAcknowledgeExternalTools,
    onPause,
    onArchive,
    onReload
  }: Props = $props();

  const widget = $derived(autosave.widget);
  const blockers = $derived(widget.activation_blockers ?? []);
  const refusals = $derived([...new Set(Object.values(autosave.refusals))]);
  const canActivate = $derived(isAdmin && blockers.length === 0 && !autosave.hasPending);
  // The assistant's tools at MCP servers outside Eneo, as the backend lists
  // them, and whether an admin's acknowledgement covers them all. Visitors
  // reach only acknowledged tools, so activation stops at a dialog until the
  // admin has read the list and said yes, and a live widget with newer tools
  // offers the same dialog without pausing.
  const externalTools = $derived(widget.external_tools ?? []);
  const needsAcknowledgement = $derived(
    externalTools.length > 0 && !(widget.external_tools_acknowledged ?? true)
  );
  const canAcknowledgeLive = $derived(
    isAdmin && widget.status === "active" && needsAcknowledgement
  );

  let archiveOpen = $state(false);
  let consentOpen = $state(false);
  let acknowledged = $state(false);
  // What the dialog lists is what gets acknowledged; the API refuses any
  // other list, so one that changed meanwhile is shown again in its place.
  let shown = $state<Widget["external_tools"]>([]);
  const ACK_CHECKBOX_ID = "widget-external-tools-ack";
  let shownChanged = $state(false);
  // Each refusal renders the alert anew, so a second one is announced too.
  let changes = $state(0);
  let activatesAfter = $state(false);
  // A busy button is disabled, which drops focus to the page, so the button
  // an action started from is taken when it is pressed. Once the action has
  // settled focus goes back to it or, when it is gone or still disabled, to a
  // fallback: activating swaps Activate for Pause and pausing the reverse, and
  // an acknowledgement on a live widget takes away the button with the blocker
  // it answered. The dialog's opener gets focus back when the dialog closes.
  let opener: HTMLElement | null = null;
  let heading = $state<HTMLElement>();
  const pressed = () => {
    const active = document.activeElement;
    return active instanceof HTMLElement && active !== document.body ? active : null;
  };
  const usable = (element: HTMLElement | null): element is HTMLElement =>
    !!element?.isConnected && !element.matches(":disabled");
  const checkbox = () => document.getElementById(ACK_CHECKBOX_ID);

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

  function review(servers: Widget["external_tools"], changed: boolean) {
    shown = $state.snapshot(servers);
    shownChanged = changed;
    if (changed) changes += 1;
    acknowledged = false;
    consentOpen = true;
  }

  // Activates, or shows the current list again when it changed under the admin.
  async function activateOrReview() {
    try {
      await onActivate();
      consentOpen = false;
    } catch (error) {
      const servers = currentExternalTools(error);
      if (!servers) throw error;
      activatesAfter = true;
      review(servers, true);
    }
  }

  const activate = createAsyncState(async () => {
    try {
      await autosave.flush();
      if (autosave.hasPending) return;
      if (needsAcknowledgement) {
        activatesAfter = true;
        review(externalTools, false);
        return;
      }
      await activateOrReview();
    } catch (error) {
      toastWidgetError(error, m.widget_admin_could_not_activate());
    }
  });
  async function startActivation() {
    opener = pressed();
    await activate();
    if (consentOpen) return;
    const button = opener;
    opener = null;
    await refocus(button, () => heading);
  }
  const acknowledge = createAsyncState(async () => {
    try {
      await onAcknowledgeExternalTools(shown);
    } catch (error) {
      const servers = currentExternalTools(error);
      if (servers) review(servers, true);
      else toastWidgetError(error, m.widget_admin_external_tools_could_not_acknowledge());
      return;
    }
    if (!activatesAfter) {
      consentOpen = false;
      return;
    }
    try {
      await activateOrReview();
    } catch (error) {
      // The acknowledgement holds; activation failed for another reason.
      consentOpen = false;
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
  async function startPause() {
    const button = pressed();
    await pause();
    await refocus(button, () => heading);
  }
  async function confirmTools() {
    const button = pressed();
    await acknowledge();
    // A dialog that closed hands focus back itself. One still open after a
    // refusal keeps focus inside, on the checkbox when the button waits for it.
    if (consentOpen) await refocus(button, checkbox);
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
    <!-- An active widget with blockers is live but not serving as configured
         (an unpublished assistant, no allowed website, no AI disclosure,
         tools no admin has acknowledged). -->
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
      {#if canAcknowledgeLive}
        <Button
          class="mt-2"
          variant="outline"
          size="sm"
          onclick={() => {
            opener = pressed();
            activatesAfter = false;
            review(externalTools, false);
          }}>{m.widget_admin_external_tools_review()}</Button
        >
      {/if}
    </div>
  {:else if adminOnlyNote}
    <p id="widget-status-admin-only" class="text-secondary text-sm">{adminOnlyNote}</p>
  {:else if externalToolsNote}
    <p id="widget-status-external-tools" class="text-secondary text-sm">{externalToolsNote}</p>
  {/if}
</section>

<AlertDialog.Root bind:open={consentOpen}>
  <AlertDialog.Content
    escapeKeydownBehavior={acknowledge.isLoading ? "ignore" : "close"}
    onCloseAutoFocus={(event) => {
      event.preventDefault();
      const button = opener;
      opener = null;
      void tick().then(() => (usable(button) ? button : heading)?.focus());
    }}
  >
    <AlertDialog.Header>
      <AlertDialog.Title>{m.widget_admin_external_tools_title()}</AlertDialog.Title>
      <AlertDialog.Description
        >{m.widget_admin_external_tools_description()}</AlertDialog.Description
      >
    </AlertDialog.Header>
    {#if shownChanged}
      {#key changes}
        <p
          role="alert"
          class="bg-warning-dimmer text-warning-stronger rounded-md px-3 py-2 text-sm"
        >
          {m.widget_admin_external_tools_changed()}
        </p>
      {/key}
    {/if}
    {#if shown.length > 0}
      <ul class="flex flex-col gap-2 text-sm" aria-label={m.widget_admin_external_tools_servers()}>
        {#each shown as server (server.id)}
          <li class="border-default rounded-md border px-3 py-2">
            <p class="font-medium">{server.name}</p>
            <p class="text-secondary">
              {m.widget_admin_external_tools_tools({
                tools: server.tools.map((tool) => tool.name).join(", ")
              })}
            </p>
          </li>
        {/each}
      </ul>
      <div class="flex items-start gap-3">
        <Checkbox
          id={ACK_CHECKBOX_ID}
          class="mt-0.5"
          bind:checked={acknowledged}
          aria-describedby="widget-external-tools-ack-help"
        />
        <div class="flex flex-col gap-1">
          <Label for={ACK_CHECKBOX_ID} class="leading-snug"
            >{m.widget_admin_external_tools_acknowledge()}</Label
          >
          <p id="widget-external-tools-ack-help" class="text-secondary text-sm">
            {m.widget_admin_external_tools_acknowledge_help()}
          </p>
        </div>
      </div>
    {:else}
      <!-- Every tool was switched off meanwhile: nothing is left to accept. -->
      <p class="text-secondary text-sm">{m.widget_admin_external_tools_none_left()}</p>
    {/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={acknowledge.isLoading}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        disabled={(shown.length > 0 && !acknowledged) || acknowledge.isLoading}
        onclick={(event) => {
          event.preventDefault();
          void confirmTools();
        }}
      >
        {!activatesAfter
          ? m.widget_admin_external_tools_confirm()
          : widget.status === "paused"
            ? m.widget_admin_resume()
            : m.widget_admin_activate()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

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
