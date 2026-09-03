<script lang="ts" module>
  /** What the dialog shows after the reader confirms: the request in flight,
   *  or the created flow about to open. The parent owns the transitions. */
  export type ApprovePhase = "idle" | "pending" | "created";
</script>

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import IconCheck from "@lucide/svelte/icons/check";
  import IconLoaderCircle from "@lucide/svelte/icons/loader-circle";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  interface Props {
    open: boolean;
    /** Create writes a new draft flow; edit writes into an existing one. */
    mode: "create" | "edit";
    stepCount: number;
    phase?: ApprovePhase;
    onconfirm: () => void;
  }

  let { open = $bindable(false), mode, stepCount, phase = "idle", onconfirm }: Props = $props();

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
    <ul class="text-secondary flex list-none flex-col gap-1.5 p-0 text-[0.8125rem]">
      <li>
        {isCreate
          ? m.ai_builder_approve_dialog_steps({ count: stepCount })
          : m.ai_builder_approve_dialog_steps_edit({ count: stepCount })}
      </li>
      <li>{m.ai_builder_approve_dialog_no_data()}</li>
      <li>{m.ai_builder_approve_dialog_step_editable()}</li>
    </ul>
    <!-- Mounted from the start so the announcement lands when the text
         changes; reserving its height keeps the footer from jumping. -->
    <p
      class="text-primary flex min-h-5 items-center gap-2 text-[0.8125rem] font-medium"
      role="status"
      aria-live="polite"
    >
      {#if phase === "created"}
        <span
          class="text-positive-default motion-safe:animate-in motion-safe:fade-in-0 flex items-center gap-2 motion-safe:duration-200"
        >
          <IconCheck class="size-4 shrink-0" aria-hidden="true" />
          {m.ai_builder_approve_dialog_created()}
        </span>
      {:else if phase === "pending"}
        <span
          class="motion-safe:animate-in motion-safe:fade-in-0 flex items-center gap-2 motion-safe:duration-200"
        >
          <IconLoaderCircle
            class="text-accent-stronger size-4 shrink-0 animate-spin motion-reduce:animate-none"
            aria-hidden="true"
          />
          {m.ai_builder_approve_dialog_pending_hint()}
        </span>
      {/if}
    </p>
    <AlertDialog.Footer>
      <!-- Plain Buttons rather than AlertDialog.Cancel/Action: those close
           the dialog on click, and the dialog now stays open while the flow
           is written. The parent closes it; cancel only closes while idle. -->
      <Button variant="outline" disabled={busy} onclick={() => (open = false)}>
        {m.ai_builder_approve_dialog_cancel()}
      </Button>
      <Button disabled={busy} onclick={onconfirm}>
        {#if busy}
          <IconLoaderCircle
            class="size-3.5 animate-spin motion-reduce:animate-none"
            aria-hidden="true"
          />
        {/if}
        {#if busy}
          {isCreate ? m.ai_builder_creating() : m.ai_builder_applying()}
        {:else}
          {isCreate
            ? m.ai_builder_approve_dialog_confirm()
            : m.ai_builder_approve_dialog_confirm_edit()}
        {/if}
      </Button>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
