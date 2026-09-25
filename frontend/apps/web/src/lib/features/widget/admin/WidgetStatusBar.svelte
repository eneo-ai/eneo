<!--
  Lifecycle of one widget: status, save state, why it cannot be activated
  yet (or, once active, what keeps it from serving properly), and the
  lifecycle actions. Organisation administrators activate and archive; other
  editors ask for activation, and every editor can pause, the kill switch.
-->
<script lang="ts">
  import { Archive, Clock, Undo2 } from "@lucide/svelte";
  import { tick } from "svelte";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { blockerLabel } from "./blockers";
  import { toastWidgetError, widgetErrorMessage } from "./errors";
  import { activationRequestState, widgetStatusLabel } from "./status";
  import TimedText from "./TimedText.svelte";
  import type { WidgetAutosave } from "./widgetAutosave.svelte";

  type Props = {
    autosave: WidgetAutosave;
    isAdmin: boolean;
    currentUserId: string;
    onActivate: () => Promise<void>;
    onPause: () => Promise<void>;
    onArchive: () => Promise<void>;
    onReload: () => Promise<void>;
    onRequestActivation: () => Promise<void>;
    onWithdrawRequest: () => Promise<void>;
  };

  let {
    autosave,
    isAdmin,
    currentUserId,
    onActivate,
    onPause,
    onArchive,
    onReload,
    onRequestActivation,
    onWithdrawRequest
  }: Props = $props();

  const widget = $derived(autosave.widget);
  const blockers = $derived(widget.activation_blockers ?? []);
  const refusals = $derived([...new Set(Object.values(autosave.refusals))]);
  const inactive = $derived(widget.status === "draft" || widget.status === "paused");
  const requestState = $derived(activationRequestState(widget));
  const requestedAt = $derived(requestState.kind === "requested" ? requestState.at : null);
  const returnedAt = $derived(requestState.kind === "returned" ? requestState.at : null);
  // Unsaved edits do not block: activating and requesting save them first,
  // and the server checks the saved widget.
  const blocked = $derived(blockers.length > 0);

  let archiveOpen = $state(false);
  let announcement = $state("");
  let requestButton = $state<HTMLElement | null>(null);
  let withdrawButton = $state<HTMLElement | null>(null);

  async function announce(message: string) {
    // Cleared first so the same message twice in a row is read out again.
    announcement = "";
    await tick();
    announcement = message;
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
  const request = createAsyncState(async () => {
    try {
      await autosave.flush();
      if (autosave.hasPending) return;
      await onRequestActivation();
    } catch (error) {
      toastWidgetError(error, m.widget_request_could_not());
      return;
    }
    await announce(m.widget_request_sent());
    // The button that was pressed is replaced by the one that undoes it.
    withdrawButton?.focus();
  });
  const withdraw = createAsyncState(async () => {
    try {
      await onWithdrawRequest();
    } catch (error) {
      toastWidgetError(error, m.widget_request_could_not_withdraw());
      return;
    }
    await announce(m.widget_request_withdrawn());
    requestButton?.focus();
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

  const requestedMessage = (date: string) =>
    widget.activation_requested_by_user_id === currentUserId
      ? m.widget_request_mine({ date })
      : m.widget_request_other({ date });
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
            : "outline"}>{widgetStatusLabel(widget.status)}</Badge
      >
      {#if requestedAt}
        <Badge variant="outline">
          <Clock aria-hidden="true" />
          {m.widget_request_badge()}
        </Badge>
      {/if}
      <span
        id="widget-status-save"
        class="text-secondary text-sm"
        aria-live="polite"
        aria-atomic="true"
      >
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
      {:else if inactive && isAdmin}
        <!-- aria-disabled rather than disabled: it stays focusable and is described by what blocks it. -->
        <Button
          variant="default"
          aria-disabled={blocked || activate.isLoading}
          aria-describedby={blocked ? "widget-status-blockers" : undefined}
          class={blocked || activate.isLoading ? "opacity-50" : undefined}
          onclick={() => {
            if (!blocked && !activate.isLoading) void activate();
          }}
        >
          {widget.status === "paused" ? m.widget_admin_resume() : m.widget_admin_activate()}
        </Button>
      {:else if inactive && requestedAt}
        <Button
          variant="outline"
          bind:ref={withdrawButton}
          aria-disabled={withdraw.isLoading}
          aria-busy={withdraw.isLoading}
          onclick={() => {
            if (!withdraw.isLoading) void withdraw();
          }}
        >
          {withdraw.isLoading ? m.widget_request_withdrawing() : m.widget_request_withdraw()}
        </Button>
      {:else if inactive}
        <Button
          variant={blocked ? "outline" : "default"}
          bind:ref={requestButton}
          aria-disabled={blocked || request.isLoading}
          aria-busy={request.isLoading}
          aria-describedby={blocked
            ? "widget-status-blockers"
            : returnedAt
              ? "widget-status-returned"
              : "widget-status-request-note"}
          class={blocked ? "opacity-50" : undefined}
          onclick={() => {
            if (!blocked && !request.isLoading) void request();
          }}
        >
          {request.isLoading
            ? m.widget_request_pending()
            : widget.status === "paused"
              ? m.widget_request_button_resume()
              : m.widget_request_button()}
        </Button>
      {/if}
      {#if isAdmin && widget.status !== "archived"}
        <!-- Outline: red text on these surfaces is below 4.5:1 in dark mode. The
             dialog's confirm button carries the warning colour instead. -->
        <Button variant="outline" onclick={() => (archiveOpen = true)}>
          <Archive aria-hidden="true" data-icon="inline-start" />
          {m.widget_admin_archive()}
        </Button>
      {/if}
    </div>
  </div>

  {#if requestedAt}
    <div class="bg-secondary flex items-start gap-2 rounded-lg px-3 py-2 text-sm">
      <Clock class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div class="flex min-w-0 flex-col gap-1">
        <p>
          <TimedText message={requestedMessage} value={requestedAt} />
          {#if isAdmin}
            <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed id -->
            <a
              class="text-accent-stronger underline underline-offset-2"
              href={localizeHref(`/admin/widgets/${widget.id}`)}
              >{m.widget_request_admin_review()}</a
            >
            <!-- eslint-enable svelte/no-navigation-without-resolve -->
          {/if}
        </p>
        {#if !isAdmin}
          <p class="text-secondary">{m.widget_request_keep_editing()}</p>
        {/if}
      </div>
    </div>
  {/if}

  {#if returnedAt}
    <div
      id="widget-status-returned"
      class="bg-warning-dimmer text-warning-stronger flex items-start gap-2 rounded-lg px-3 py-3 text-sm"
    >
      <Undo2 class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div class="flex min-w-0 flex-col gap-2">
        <h3 class="font-medium">
          <TimedText
            message={(date) => m.widget_request_returned_title({ date })}
            value={returnedAt}
          />
        </h3>
        {#if widget.activation_decline_reason}
          <blockquote
            class="border-warning-default border-l-2 pl-3 break-words whitespace-pre-wrap"
          >
            {widget.activation_decline_reason}
          </blockquote>
        {/if}
        {#if !isAdmin}
          <p>{m.widget_request_returned_next()}</p>
        {/if}
      </div>
    </div>
  {/if}

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
  {:else if inactive && !isAdmin && !requestedAt && !returnedAt}
    <p id="widget-status-request-note" class="text-secondary text-sm">{m.widget_request_note()}</p>
  {/if}

  <p role="status" class="sr-only">{announcement}</p>
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
        variant="destructive"
        disabled={archive.isLoading}
        onclick={(event) => {
          event.preventDefault();
          void archive();
        }}>{m.widget_admin_archive()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
