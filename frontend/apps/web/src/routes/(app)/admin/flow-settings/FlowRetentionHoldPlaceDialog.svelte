<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";

  import {
    HOLD_REASON_MAX,
    HOLD_RUNS_MAX,
    endOfLocalDay,
    holdErrorMessage,
    isValidReason,
    latestReviewDate,
    localDate
  } from "./flowRetentionHold";

  type Props = {
    open: boolean;
    flow: { id: string; name: string } | null;
    maxReviewDays: number;
    onPlaced: () => void;
  };

  let { open = $bindable(), flow, maxReviewDays, onPlaced }: Props = $props();
  const eneo = getEneo();
  const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

  let scope = $state<"flow" | "runs">("flow");
  let runIdsText = $state("");
  let reason = $state("");
  let reviewDate = $state("");
  let endDate = $state("");
  let attempted = $state(false);
  let placing = $state(false);
  let refusal = $state<string | null>(null);
  // Read when the dialog opens, so a page left open over midnight offers today.
  let now = $state(new Date());

  // Every opening starts from a clean form and the current date.
  $effect(() => {
    if (!open) return;
    now = new Date();
    scope = "flow";
    runIdsText = "";
    reason = "";
    reviewDate = "";
    endDate = "";
    attempted = false;
    refusal = null;
  });

  const today = $derived(localDate(now));
  const latestReview = $derived(latestReviewDate(now, maxReviewDays));
  const runIds = $derived(
    runIdsText
      .split(/[\s,;]+/)
      .map((value) => value.trim())
      .filter(Boolean)
  );
  const runIdsValid = $derived(
    scope === "flow" ||
      (runIds.length >= 1 &&
        runIds.length <= HOLD_RUNS_MAX &&
        runIds.every((value) => UUID_PATTERN.test(value)))
  );
  const reasonValid = $derived(isValidReason(reason));
  const reviewValid = $derived(
    reviewDate !== "" && reviewDate >= today && reviewDate <= latestReview
  );
  const endValid = $derived(endDate === "" || endDate >= today);

  async function place(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    attempted = true;
    if (!flow || placing || !runIdsValid || !reasonValid || !reviewValid || !endValid) {
      return;
    }
    placing = true;
    refusal = null;
    try {
      await eneo.settings.placeFlowRetentionHold({
        flowId: flow.id,
        runIds: scope === "runs" ? runIds : null,
        reason: reason.trim(),
        reviewBy: endOfLocalDay(reviewDate),
        endsAt: endDate ? endOfLocalDay(endDate) : null
      });
      open = false;
      toast.success(m.flow_retention_hold_placed());
      onPlaced();
    } catch (error) {
      const message = holdErrorMessage(error);
      if (message) refusal = message;
      else toastError(error);
    } finally {
      placing = false;
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-lg">
    <form class="grid gap-4" onsubmit={place} novalidate>
      <Dialog.Header>
        <Dialog.Title>{m.flow_retention_hold_dialog_title()}</Dialog.Title>
        <Dialog.Description>{m.flow_retention_hold_dialog_description()}</Dialog.Description>
      </Dialog.Header>

      {#if refusal}
        <Alert.Root variant="destructive">
          <Alert.Description>{refusal}</Alert.Description>
        </Alert.Root>
      {/if}

      <div class="bg-secondary border-default rounded-md border p-3">
        <p class="text-secondary text-xs">{m.flow_retention_hold_flow_label()}</p>
        <p class="text-primary text-sm font-medium">{flow?.name}</p>
      </div>

      <Field.Set>
        <Field.Legend variant="label">{m.flow_retention_hold_scope_label()}</Field.Legend>
        <RadioGroup.Root bind:value={scope} class="grid gap-2">
          <Field.Field orientation="horizontal">
            <RadioGroup.Item value="flow" id="flow-retention-hold-scope-flow" />
            <Field.Content>
              <Field.Label for="flow-retention-hold-scope-flow">
                {m.flow_retention_hold_scope_flow()}
              </Field.Label>
              <Field.Description>{m.flow_retention_hold_scope_flow_description()}</Field.Description
              >
            </Field.Content>
          </Field.Field>
          <Field.Field orientation="horizontal">
            <RadioGroup.Item value="runs" id="flow-retention-hold-scope-runs" />
            <Field.Content>
              <Field.Label for="flow-retention-hold-scope-runs">
                {m.flow_retention_hold_scope_runs()}
              </Field.Label>
              <Field.Description>{m.flow_retention_hold_scope_runs_description()}</Field.Description
              >
            </Field.Content>
          </Field.Field>
        </RadioGroup.Root>
      </Field.Set>

      {#if scope === "runs"}
        <Field.Field data-invalid={attempted && !runIdsValid}>
          <Field.Label for="flow-retention-hold-run-ids">
            {m.flow_retention_hold_run_ids_label()}
          </Field.Label>
          <Textarea
            id="flow-retention-hold-run-ids"
            rows={3}
            class="font-mono text-xs"
            bind:value={runIdsText}
            aria-invalid={attempted && !runIdsValid}
          />
          {#if attempted && !runIdsValid}
            <Field.Error
              >{m.flow_retention_hold_run_ids_invalid({ max: HOLD_RUNS_MAX })}</Field.Error
            >
          {:else}
            <Field.Description>
              {m.flow_retention_hold_run_ids_description({ max: HOLD_RUNS_MAX })}
            </Field.Description>
          {/if}
        </Field.Field>
      {/if}

      <Field.Field data-invalid={attempted && !reasonValid}>
        <Field.Label for="flow-retention-hold-reason">
          {m.flow_retention_hold_reason_label()}
        </Field.Label>
        <Textarea
          id="flow-retention-hold-reason"
          rows={3}
          maxlength={HOLD_REASON_MAX}
          bind:value={reason}
          aria-invalid={attempted && !reasonValid}
        />
        {#if attempted && !reasonValid}
          <Field.Error>{m.flow_retention_hold_reason_invalid({ max: HOLD_REASON_MAX })}</Field.Error
          >
        {:else}
          <Field.Description>{m.flow_retention_hold_reason_description()}</Field.Description>
        {/if}
      </Field.Field>

      <div class="grid gap-4 sm:grid-cols-2">
        <Field.Field data-invalid={attempted && !reviewValid}>
          <Field.Label for="flow-retention-hold-review">
            {m.flow_retention_hold_review_label()}
          </Field.Label>
          <Input
            id="flow-retention-hold-review"
            type="date"
            min={today}
            max={latestReview}
            bind:value={reviewDate}
            aria-invalid={attempted && !reviewValid}
          />
          {#if attempted && !reviewValid}
            <Field.Error>
              {m.flow_retention_hold_review_invalid({ days: maxReviewDays })}
            </Field.Error>
          {:else}
            <Field.Description>
              {m.flow_retention_hold_review_description({ days: maxReviewDays })}
            </Field.Description>
          {/if}
        </Field.Field>

        <Field.Field data-invalid={attempted && !endValid}>
          <Field.Label for="flow-retention-hold-end"
            >{m.flow_retention_hold_end_label()}</Field.Label
          >
          <Input
            id="flow-retention-hold-end"
            type="date"
            min={today}
            bind:value={endDate}
            aria-invalid={attempted && !endValid}
          />
          {#if attempted && !endValid}
            <Field.Error>{m.flow_retention_hold_end_invalid()}</Field.Error>
          {:else}
            <Field.Description>{m.flow_retention_hold_end_description()}</Field.Description>
          {/if}
        </Field.Field>
      </div>

      <Dialog.Footer>
        <Button type="button" variant="outline" onclick={() => (open = false)}>
          {m.flow_retention_hold_cancel()}
        </Button>
        <Button type="submit" disabled={placing}>
          {placing ? m.flow_retention_hold_saving() : m.flow_retention_hold_place()}
        </Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
