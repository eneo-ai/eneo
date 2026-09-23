<script lang="ts" module>
  /** What the dialog shows after the reader confirms: the request in flight,
   *  or the created flow about to open. The parent owns the transitions. */
  export type ApprovePhase = "idle" | "pending" | "created";
</script>

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import IconCheck from "@lucide/svelte/icons/check";
  import IconInfo from "@lucide/svelte/icons/info";
  import IconLoaderCircle from "@lucide/svelte/icons/loader-circle";
  import IconPencil from "@lucide/svelte/icons/pencil";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  interface Props {
    open: boolean;
    /** Create writes a new draft flow; edit writes into an existing one. */
    mode: "create" | "edit";
    stepCount: number;
    /** Edit mode: the steps the change adds, modifies or removes, from the diff. */
    changedStepCount?: number;
    unchangedStepCount?: number;
    /** Edit mode: "Steg 3: Skriv sammanfattning ändras" when one step changes. */
    changedStepLine?: string | null;
    phase?: ApprovePhase;
    onconfirm: () => void;
  }

  let {
    open = $bindable(false),
    mode,
    stepCount,
    changedStepCount = 0,
    unchangedStepCount = 0,
    changedStepLine = null,
    phase = "idle",
    onconfirm
  }: Props = $props();

  const isCreate = $derived(mode === "create");
  // Once the reader has confirmed, the dialog is the progress surface: it
  // stays put until the flow opens or the parent closes it on failure.
  const busy = $derived(phase !== "idle");
  const closeBehavior = $derived<"close" | "ignore">(busy ? "ignore" : "close");
</script>

<AlertDialog.Root bind:open>
  <AlertDialog.Content
    class="max-w-[28.75rem]"
    interactOutsideBehavior={closeBehavior}
    escapeKeydownBehavior={closeBehavior}
    aria-busy={busy}
  >
    <AlertDialog.Header>
      <AlertDialog.Title>
        {isCreate ? m.ai_builder_approve_dialog_title() : m.ai_builder_approve_dialog_title_edit()}
      </AlertDialog.Title>
      <AlertDialog.Description>
        {isCreate ? m.ai_builder_approve_dialog_body() : m.ai_builder_approve_dialog_body_edit()}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <div class="flex flex-col gap-1.5 text-[0.8125rem]">
      {#if isCreate}
        <ul class="text-secondary flex list-none flex-col gap-1.5 p-0">
          <li>{m.ai_builder_approve_dialog_steps({ count: stepCount })}</li>
          <li>{m.ai_builder_approve_dialog_no_data()}</li>
        </ul>
      {:else}
        <!-- What changes and what stays, a step named when it is one. An
             edit's description already says no run starts. -->
        <ul class="text-primary flex list-none flex-col gap-2 p-0">
          <li class="flex items-start gap-2.5">
            <IconPencil class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {changedStepLine ?? m.ai_builder_approve_dialog_steps_edit_all({ count: changedStepCount })}
          </li>
          {#if unchangedStepCount > 0}
            <li class="flex items-start gap-2.5">
              <IconCheck class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
              {unchangedStepCount === 1
                ? m.ai_builder_approve_dialog_unchanged_one()
                : m.ai_builder_approve_dialog_unchanged({ count: unchangedStepCount })}
            </li>
          {/if}
        </ul>
      {/if}
      <!-- The last line is the dialog's status: what stays editable until the
           reader confirms, then how the work goes. Mounted from the start so
           the announcement lands when the text changes; it keeps one line, so
           the footer does not jump and no empty row waits for it. -->
      <p class="flex min-h-5 items-center gap-2" role="status" aria-live="polite">
        {#if phase === "created"}
          <span
            class="text-positive-stronger motion-safe:animate-in motion-safe:fade-in-0 flex items-center gap-2 font-medium motion-safe:duration-(--duration-fast)"
          >
            <IconCheck class="size-4 shrink-0" aria-hidden="true" />
            {m.ai_builder_approve_dialog_created()}
          </span>
        {:else if phase === "pending"}
          <span
            class="text-primary motion-safe:animate-in motion-safe:fade-in-0 flex items-center gap-2 font-medium motion-safe:duration-(--duration-fast)"
          >
            <IconLoaderCircle
              class="text-accent-stronger size-4 shrink-0 animate-spin motion-reduce:animate-none"
              aria-hidden="true"
            />
            {isCreate
              ? m.ai_builder_approve_dialog_pending_hint()
              : m.ai_builder_approve_dialog_pending_hint_edit()}
          </span>
        {:else}
          <span class="text-secondary flex items-start gap-2.5">
            <IconInfo class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {m.ai_builder_approve_dialog_step_editable()}
          </span>
        {/if}
      </p>
    </div>
    <AlertDialog.Footer class="border-border">
      <!-- Plain Buttons rather than AlertDialog.Cancel/Action: those close
           the dialog on click, and the dialog now stays open while the flow
           is written. The parent closes it; cancel only closes while idle. -->
      <Button variant="outline" disabled={busy} onclick={() => (open = false)}>
        {m.ai_builder_approve_dialog_cancel()}
      </Button>
      <Button disabled={busy} onclick={onconfirm}>
        {#if phase === "created"}
          <IconCheck class="size-3.5" aria-hidden="true" />
          {m.ai_builder_approve_dialog_created_action()}
        {:else if phase === "pending"}
          <IconLoaderCircle
            class="size-3.5 animate-spin motion-reduce:animate-none"
            aria-hidden="true"
          />
          {isCreate ? m.ai_builder_creating() : m.ai_builder_updating_flow()}
        {:else}
          {isCreate
            ? m.ai_builder_approve_dialog_confirm()
            : m.ai_builder_approve_dialog_confirm_edit()}
        {/if}
      </Button>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
