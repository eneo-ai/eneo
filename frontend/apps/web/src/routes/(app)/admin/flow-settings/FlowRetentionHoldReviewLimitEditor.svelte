<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";

  import { holdErrorCode, holdErrorMessage } from "./flowRetentionHold";

  // The guardrail on legal holds: how far ahead a review date may be set.
  // Owned by retention_manage; the server checks every change again.
  type Limit = { days: number; is_default: boolean | null };
  type Props = { limit: Limit | null; onChange: (limit: Limit) => void };

  let { limit, onChange }: Props = $props();
  const eneo = getEneo();
  const MAX_DAYS = 2555;
  const DEFAULT_DAYS = 365;

  let input = $state<number | null>(untrack(() => limit?.days ?? null));
  // The server value the draft was last taken from. While the draft still
  // equals it, a refreshed limit replaces it; a deliberate edit is kept.
  let synced = $state<number | null>(untrack(() => limit?.days ?? null));

  $effect(() => {
    const days = limit?.days ?? null;
    if (days === untrack(() => synced)) return;
    if (untrack(() => input) === untrack(() => synced)) input = days;
    synced = days;
  });
  let saving = $state(false);
  let loading = $state(false);
  let refusal = $state<string | null>(null);

  const valid = $derived(
    typeof input === "number" && Number.isInteger(input) && input >= 1 && input <= MAX_DAYS
  );
  const unchanged = $derived(limit !== null && input === limit.days);

  // The limit belongs to retention_manage, so a refusal names that permission.
  function refusalMessage(error: unknown): string | null {
    const code = holdErrorCode(error);
    if (code === "retention_permission_required" || code === "retention_person_required") {
      return m.flow_retention_hold_max_review_not_allowed();
    }
    return holdErrorMessage(error);
  }

  async function reload(): Promise<void> {
    loading = true;
    refusal = null;
    try {
      const loaded = await eneo.settings.getFlowRetentionHoldReviewLimit();
      input = synced = loaded.days;
      onChange(loaded);
    } catch (error) {
      refusal = refusalMessage(error);
      if (!refusal) toastError(error);
    } finally {
      loading = false;
    }
  }

  async function replace(days: number | null): Promise<void> {
    if (saving) return;
    saving = true;
    refusal = null;
    try {
      const saved = await eneo.settings.replaceFlowRetentionHoldReviewLimit({ days });
      input = synced = saved.days;
      onChange(saved);
      toast.success(m.flow_retention_hold_max_review_saved());
    } catch (error) {
      refusal = refusalMessage(error);
      if (!refusal) toastError(error);
    } finally {
      saving = false;
    }
  }

  function save(event: SubmitEvent): void {
    event.preventDefault();
    if (!valid || unchanged || input === null) return;
    void replace(input);
  }
</script>

<div class="mx-4 space-y-2 lg:mx-0.5">
  {#if refusal}
    <Alert.Root variant="destructive" class="max-w-3xl">
      <Alert.Description>{refusal}</Alert.Description>
    </Alert.Root>
  {/if}
  {#if limit === null}
    <Alert.Root class="max-w-3xl">
      <Alert.Description>{m.flow_retention_hold_max_review_unavailable()}</Alert.Description>
      <Button type="button" variant="outline" size="sm" disabled={loading} onclick={reload}>
        {m.flow_retention_hold_refresh()}
      </Button>
    </Alert.Root>
  {:else}
    <form class="flex flex-wrap items-end gap-3" onsubmit={save} novalidate>
      <Field.Field class="w-auto" data-invalid={!valid}>
        <Field.Label for="flow-retention-hold-max-review-days">
          {m.flow_retention_hold_max_review_label()}
        </Field.Label>
        <Input
          id="flow-retention-hold-max-review-days"
          type="number"
          inputmode="numeric"
          min={1}
          max={MAX_DAYS}
          class="w-32"
          bind:value={input}
          aria-invalid={!valid}
        />
        {#if !valid}
          <Field.Error>{m.flow_retention_hold_max_review_invalid({ max: MAX_DAYS })}</Field.Error>
        {:else}
          <Field.Description>
            {limit.is_default === true
              ? m.flow_retention_hold_max_review_default_note({ days: DEFAULT_DAYS })
              : m.flow_retention_hold_max_review_description()}
          </Field.Description>
        {/if}
      </Field.Field>
      <Button type="submit" variant="outline" size="sm" disabled={!valid || unchanged || saving}>
        {m.flow_retention_hold_max_review_save()}
      </Button>
      {#if limit.is_default !== true}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={saving}
          onclick={() => replace(null)}
        >
          {m.flow_retention_hold_max_review_use_default({ days: DEFAULT_DAYS })}
        </Button>
      {/if}
    </form>
  {/if}
</div>
