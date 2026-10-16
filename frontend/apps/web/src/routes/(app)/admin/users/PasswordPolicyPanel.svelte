<script lang="ts">
  import type { PasswordLifecyclePolicy } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button";
  import * as Field from "$lib/components/ui/field";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import { m } from "$lib/paraglide/messages";
  import { Check, CircleAlert } from "@lucide/svelte";

  let { policy }: { policy: PasswordLifecyclePolicy } = $props();

  const eneo = getEneo();
  const id = $props.id();

  // The loaded policy seeds the draft once; later edits live in the draft
  // until saved, so a list refresh never discards what the admin is typing.
  // svelte-ignore state_referenced_locally
  let saved = $state<PasswordLifecyclePolicy>(policy);
  // svelte-ignore state_referenced_locally
  let requireChange = $state(policy.require_change_after_admin_set !== false);
  // svelte-ignore state_referenced_locally
  let maxAgeDays = $state(policy.max_age_days == null ? "" : String(policy.max_age_days));
  let saving = $state(false);
  let errorMessage = $state<string | null>(null);
  let successMessage = $state<string | null>(null);
  let submitted = $state(false);

  /** Empty means "never"; anything else must be a whole number of days within the backend's range. */
  function parseMaxAge(value: string): number | null | undefined {
    const trimmed = value.trim();
    if (trimmed === "") return null;
    if (!/^\d+$/.test(trimmed)) return undefined;
    const days = Number(trimmed);
    return days >= 1 && days <= 3650 ? days : undefined;
  }

  const parsedMaxAge = $derived(parseMaxAge(maxAgeDays));
  const maxAgeError = $derived(submitted && parsedMaxAge === undefined);
  const hasChanges = $derived(
    requireChange !== (saved.require_change_after_admin_set !== false) ||
      parsedMaxAge !== (saved.max_age_days ?? null)
  );

  async function save(event: SubmitEvent) {
    event.preventDefault();
    submitted = true;
    errorMessage = null;
    successMessage = null;
    if (parsedMaxAge === undefined || saving) return;

    saving = true;
    try {
      saved = await eneo.users.updatePasswordLifecyclePolicy({
        require_change_after_admin_set: requireChange,
        max_age_days: parsedMaxAge
      });
      requireChange = saved.require_change_after_admin_set !== false;
      maxAgeDays = saved.max_age_days == null ? "" : String(saved.max_age_days);
      submitted = false;
      successMessage = m.admin_password_policy_updated();
    } catch (error) {
      errorMessage = getErrorMessage(error);
    } finally {
      saving = false;
    }
  }
</script>

<section
  aria-labelledby={`${id}-title`}
  data-tour="admin-password-policy"
  class="border-default bg-primary mt-8 rounded-lg border p-5"
>
  <h2 id={`${id}-title`} class="text-base font-semibold">{m.admin_password_policy_title()}</h2>
  <p class="text-muted-foreground mt-1 text-sm">{m.admin_password_policy_description()}</p>

  <form class="mt-5 space-y-5" onsubmit={save} novalidate>
    <Field.Group class="gap-5">
      <Field.Field orientation="horizontal">
        <Field.Content>
          <Field.Label for={`${id}-require-change`}
            >{m.admin_password_policy_require_change()}</Field.Label
          >
          <Field.Description>{m.admin_password_policy_require_change_desc()}</Field.Description>
        </Field.Content>
        <Switch
          id={`${id}-require-change`}
          checked={requireChange}
          onCheckedChange={(next) => (requireChange = next)}
          disabled={saving}
        />
      </Field.Field>

      <Field.Field data-invalid={maxAgeError || undefined}>
        <Field.Label for={`${id}-max-age`}>{m.admin_password_policy_max_age()}</Field.Label>
        <Field.Description id={`${id}-max-age-hint`}>
          {m.admin_password_policy_max_age_desc()}
        </Field.Description>
        <div class="flex items-center gap-2">
          <Input
            id={`${id}-max-age`}
            type="text"
            inputmode="numeric"
            pattern="[0-9]*"
            value={maxAgeDays}
            oninput={(event) => (maxAgeDays = event.currentTarget.value)}
            placeholder={m.admin_password_policy_never()}
            aria-invalid={maxAgeError || undefined}
            aria-describedby={`${id}-max-age-hint${maxAgeError ? ` ${id}-max-age-error` : ""}`}
            disabled={saving}
            class="w-28"
          />
          <span class="text-muted-foreground text-sm">{m.admin_password_policy_days()}</span>
        </div>
        {#if maxAgeError}
          <Field.Error id={`${id}-max-age-error`}>
            {m.admin_password_policy_max_age_invalid()}
          </Field.Error>
        {/if}
      </Field.Field>
    </Field.Group>

    <div class="flex flex-wrap items-center gap-3">
      <Button type="submit" disabled={saving || !hasChanges}>
        {saving ? m.saving() : m.save()}
      </Button>
      <p role="status" aria-live="polite" class="text-sm">
        {#if successMessage}
          <span class="text-positive-stronger inline-flex items-center gap-1">
            <Check aria-hidden="true" class="size-4" />{successMessage}
          </span>
        {:else if errorMessage}
          <span class="text-negative-stronger inline-flex items-center gap-1">
            <CircleAlert aria-hidden="true" class="size-4" />{errorMessage}
          </span>
        {/if}
      </p>
    </div>
  </form>
</section>
