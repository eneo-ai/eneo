<script lang="ts">
  import { Check, Circle } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    getPasswordPolicyChecks,
    newPasswordsMatch,
    type AvailablePasswordChangeCapability,
    type PasswordPolicyError
  } from "./passwordChange";

  let { id, password, confirmPassword, capability } = $props<{
    id: string;
    password: string;
    confirmPassword: string;
    capability: AvailablePasswordChangeCapability;
  }>();

  const checks = $derived([
    ...getPasswordPolicyChecks(password, capability),
    {
      error: "confirmation_mismatch" as const,
      satisfied: newPasswordsMatch({ newPassword: password, confirmPassword })
    }
  ]);

  function label(error: PasswordPolicyError | "confirmation_mismatch"): string {
    switch (error) {
      case "confirmation_mismatch":
        return m.password_policy_confirmation_matches();
      case "too_short":
        return m.password_policy_min_length({ min: capability.policy.minLength });
      case "too_short_bytes":
        return m.password_policy_min_bytes({ min: capability.policy.minLength });
      case "too_long_bytes":
        return m.password_policy_within_maximum();
      case "uppercase_required":
        return m.password_policy_uppercase();
      case "lowercase_required":
        return m.password_policy_lowercase();
      case "number_required":
        return m.password_policy_number();
      case "symbol_required":
        return m.password_policy_symbol();
    }
  }
</script>

<div {id} class="bg-subtle rounded-lg p-3 text-sm">
  <p class="text-default font-medium">{m.password_policy_intro()}</p>
  <ul class="mt-2 space-y-2" aria-live="polite" aria-relevant="text">
    {#each checks as check (check.error)}
      {@const fulfilled = password.length > 0 && check.satisfied}
      <li
        class={fulfilled
          ? "text-positive-stronger flex items-start gap-2"
          : "text-secondary flex items-start gap-2"}
      >
        {#if fulfilled}
          <Check class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        {:else}
          <Circle class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        {/if}
        <span>
          {label(check.error)}
          <span class="sr-only">
            — {fulfilled ? m.password_policy_fulfilled() : m.password_policy_pending()}
          </span>
        </span>
      </li>
    {/each}
  </ul>
</div>
