<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import CheckCircle2 from "lucide-svelte/icons/check-circle-2";
  import AlertCircle from "lucide-svelte/icons/alert-circle";
  import Loader2 from "lucide-svelte/icons/loader-2";
  import ListChecks from "lucide-svelte/icons/list-checks";

  /**
   * "Kontrollera flödet": saves the draft so the server validates it, then
   * shows the editor's own validation state. It never runs the flow and never
   * calls a model. A result is tied to the draft revision it was made for:
   * any later edit, pending save or rejected save invalidates it.
   */
  let {
    steps,
    issueCount,
    saveStatus,
    draftRevision,
    onCheck,
    onShowIssues
  }: {
    steps: FlowStep[];
    /** Issues the editor currently knows about (client and server). */
    issueCount: number;
    saveStatus: "saved" | "saving" | "unsaved";
    draftRevision: number;
    /** Flushes pending saves; rejects only when the draft could not be saved. */
    onCheck: () => Promise<void>;
    onShowIssues?: () => void;
  } = $props();

  let checking = $state(false);
  let checkedRevision = $state<number | null>(null);
  let saveFailed = $state(false);

  type CheckState = "empty" | "idle" | "checking" | "save_failed" | "issues" | "stale" | "clean";

  const checkState = $derived.by((): CheckState => {
    if (steps.length === 0) return "empty";
    if (checking) return "checking";
    if (saveFailed) return "save_failed";
    if (checkedRevision === null) return "idle";
    if (issueCount > 0) return "issues";
    if (saveStatus !== "saved" || draftRevision !== checkedRevision) return "stale";
    return "clean";
  });

  async function check(): Promise<void> {
    checking = true;
    saveFailed = false;
    try {
      await onCheck();
      checkedRevision = draftRevision;
    } catch {
      checkedRevision = null;
      saveFailed = true;
    } finally {
      checking = false;
    }
  }
</script>

<div class="contents">
  <Button
    variant="default"
    disabled={checking || steps.length === 0}
    onclick={check}
    class="h-9 gap-2"
  >
    {#if checking}
      <Loader2 class="size-3.5 animate-spin" aria-hidden="true" />
    {:else}
      <ListChecks class="size-3.5" aria-hidden="true" />
    {/if}
    {m.flow_check_flow()}
  </Button>

  {#if checkState === "empty"}
    <p class="text-secondary order-2 w-full text-xs leading-relaxed">{m.flow_check_empty()}</p>
  {:else if checkState === "clean"}
    <div
      class="border-positive-default/30 bg-positive-dimmer/70 text-positive-stronger order-2 flex w-full items-center gap-2 rounded-xl border px-3.5 py-2.5"
      role="status"
    >
      <CheckCircle2 class="size-4 shrink-0" aria-hidden="true" />
      <span class="text-[13px] font-medium tracking-[-0.005em]">{m.flow_check_result_clean()}</span>
    </div>
  {:else if checkState === "issues"}
    <div
      class="border-negative-default/30 bg-negative-dimmer/70 text-negative-stronger order-2 flex w-full items-center gap-2 rounded-xl border px-3.5 py-2.5"
      role="alert"
    >
      <AlertCircle class="size-4 shrink-0" aria-hidden="true" />
      <span class="text-[13px] font-medium tracking-[-0.005em]">
        {m.flow_check_result_issues({ count: String(issueCount) })}
      </span>
      {#if onShowIssues}
        <Button variant="ghost" size="sm" class="ml-auto h-7" onclick={onShowIssues}>
          {m.flow_check_show_issues()}
        </Button>
      {/if}
    </div>
  {:else if checkState === "stale"}
    <div
      class="border-warning-default/30 bg-warning-dimmer/70 text-warning-stronger order-2 flex w-full items-center gap-2 rounded-xl border px-3.5 py-2.5"
      role="status"
    >
      <AlertCircle class="size-4 shrink-0" aria-hidden="true" />
      <span class="text-[13px] font-medium tracking-[-0.005em]">{m.flow_check_result_stale()}</span>
    </div>
  {:else if checkState === "save_failed"}
    <div
      class="border-negative-default/30 bg-negative-dimmer/70 text-negative-stronger order-2 flex w-full items-center gap-2 rounded-xl border px-3.5 py-2.5"
      role="alert"
    >
      <AlertCircle class="size-4 shrink-0" aria-hidden="true" />
      <span class="text-[13px] font-medium tracking-[-0.005em]"
        >{m.flow_check_result_save_failed()}</span
      >
    </div>
  {/if}
</div>
