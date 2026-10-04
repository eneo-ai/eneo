<script lang="ts">
  import type { FlowRetentionHold } from "@eneo/eneo-js";

  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";

  import {
    HOLD_REASON_MAX,
    addLocalDays,
    endOfLocalDay,
    holdErrorCode,
    holdErrorMessage,
    holdScopeLabel,
    isValidReason,
    latestReviewDate,
    localDate
  } from "./flowRetentionHold";

  // One dialog for both changes that need a written reason: releasing a hold,
  // and moving its review date later.
  type Props = {
    hold: FlowRetentionHold | null;
    mode: "release" | "extend";
    maxReviewDays: number;
    onChanged: () => void;
    onClose: () => void;
  };

  let { hold, mode, maxReviewDays, onChanged, onClose }: Props = $props();
  const eneo = getEneo();

  let reason = $state("");
  let reviewDate = $state("");
  let attempted = $state(false);
  let saving = $state(false);
  let refusal = $state<string | null>(null);
  // Read when the dialog opens, so a page left open over midnight offers today.
  let now = $state(new Date());

  $effect(() => {
    if (!hold) return;
    now = new Date();
    reason = "";
    reviewDate = "";
    attempted = false;
    refusal = null;
  });

  const today = $derived(localDate(now));
  // The new review date must be after the current one and not in the past.
  const earliestReview = $derived.by(() => {
    if (!hold) return today;
    const dayAfterCurrent = addLocalDays(localDate(new Date(hold.review_by)), 1);
    return dayAfterCurrent > today ? dayAfterCurrent : today;
  });
  const latestReview = $derived(latestReviewDate(now, maxReviewDays));
  // The current review date can lie beyond a limit lowered after the hold was
  // placed: then no later date fits until the limit is raised.
  const noLaterDateFits = $derived(mode === "extend" && earliestReview > latestReview);
  const reasonValid = $derived(isValidReason(reason));
  const reviewValid = $derived(
    mode === "release" ||
      (reviewDate !== "" && reviewDate >= earliestReview && reviewDate <= latestReview)
  );

  async function submit(event: Event): Promise<void> {
    event.preventDefault();
    attempted = true;
    const target = hold;
    if (!target || saving || noLaterDateFits || !reasonValid || !reviewValid) return;
    saving = true;
    refusal = null;
    try {
      if (mode === "release") {
        await eneo.settings.releaseFlowRetentionHold({
          holdId: target.id,
          reason: reason.trim()
        });
        toast.success(m.flow_retention_hold_released());
      } else {
        await eneo.settings.extendFlowRetentionHoldReview({
          holdId: target.id,
          reviewBy: endOfLocalDay(reviewDate),
          reason: reason.trim()
        });
        toast.success(m.flow_retention_hold_review_extended());
      }
      onClose();
      onChanged();
    } catch (error) {
      const message = holdErrorMessage(error);
      if (message) refusal = message;
      else toastError(error);
      // The list is out of date: someone else released or ended this hold.
      const code = holdErrorCode(error);
      if (
        code === "flow_retention_hold_not_active" ||
        code === "flow_retention_hold_already_released"
      ) {
        onChanged();
      }
    } finally {
      saving = false;
    }
  }
</script>

<AlertDialog.Root
  open={hold !== null}
  onOpenChange={(open) => {
    if (!open && !saving) onClose();
  }}
>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {mode === "release"
          ? m.flow_retention_hold_release_title()
          : m.flow_retention_hold_extend_title()}
      </AlertDialog.Title>
      <AlertDialog.Description>
        {mode === "release"
          ? m.flow_retention_hold_release_description()
          : m.flow_retention_hold_extend_description()}
      </AlertDialog.Description>
    </AlertDialog.Header>
    {#if hold}
      <div class="bg-secondary border-default rounded-md border p-3">
        <p class="text-primary text-sm font-medium">{hold.flow_name}</p>
        <p class="text-secondary text-xs break-all">{holdScopeLabel(hold)}</p>
      </div>
    {/if}
    {#if refusal}
      <Alert.Root variant="destructive">
        <Alert.Description>{refusal}</Alert.Description>
      </Alert.Root>
    {/if}
    {#if noLaterDateFits}
      <Alert.Root>
        <Alert.Description>
          {m.flow_retention_hold_extend_beyond_limit({ days: maxReviewDays })}
        </Alert.Description>
      </Alert.Root>
    {:else if mode === "extend"}
      <Field.Field data-invalid={attempted && !reviewValid}>
        <Field.Label for="flow-retention-hold-new-review">
          {m.flow_retention_hold_new_review_label()}
        </Field.Label>
        <Input
          id="flow-retention-hold-new-review"
          type="date"
          min={earliestReview}
          max={latestReview}
          bind:value={reviewDate}
          aria-invalid={attempted && !reviewValid}
        />
        {#if attempted && !reviewValid}
          <Field.Error>
            {m.flow_retention_hold_new_review_invalid({ days: maxReviewDays })}
          </Field.Error>
        {/if}
      </Field.Field>
    {/if}
    <Field.Field data-invalid={attempted && !reasonValid}>
      <Field.Label for="flow-retention-hold-change-reason">
        {mode === "release"
          ? m.flow_retention_hold_release_reason_label()
          : m.flow_retention_hold_extend_reason_label()}
      </Field.Label>
      <Textarea
        id="flow-retention-hold-change-reason"
        rows={3}
        maxlength={HOLD_REASON_MAX}
        bind:value={reason}
        aria-invalid={attempted && !reasonValid}
      />
      {#if attempted && !reasonValid}
        <Field.Error>{m.flow_retention_hold_reason_invalid({ max: HOLD_REASON_MAX })}</Field.Error>
      {/if}
    </Field.Field>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={saving}>{m.flow_retention_hold_cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        variant={mode === "release" ? "destructive" : "default"}
        disabled={saving || noLaterDateFits}
        onclick={submit}
      >
        {#if saving}
          {m.flow_retention_hold_saving()}
        {:else if mode === "release"}
          {m.flow_retention_hold_release()}
        {:else}
          {m.flow_retention_hold_extend()}
        {/if}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
