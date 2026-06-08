<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import {
    getStateStyle,
    type ApiKeyStateFilterValue
  } from "$lib/features/api-keys/apiKeyTableUtils";

  let {
    value = $bindable<ApiKeyStateFilterValue>(""),
    class: className = "",
    onChange
  }: {
    value?: ApiKeyStateFilterValue;
    class?: string;
    onChange?: (next: ApiKeyStateFilterValue) => void;
  } = $props();

  const options = $derived<{ value: ApiKeyStateFilterValue; label: string }[]>([
    { value: "", label: m.api_keys_admin_state_all() },
    { value: "active", label: m.api_keys_admin_state_active() },
    { value: "suspended", label: m.api_keys_admin_state_suspended() },
    { value: "expired", label: m.api_keys_admin_state_expired() },
    { value: "revoked", label: m.api_keys_admin_state_revoked() }
  ]);

  function select(next: ApiKeyStateFilterValue) {
    if (value === next) return;
    value = next;
    onChange?.(next);
  }
</script>

<div
  role="group"
  aria-label={m.api_keys_admin_label_state()}
  class="flex flex-wrap gap-2 {className}"
>
  {#each options as option (option.value)}
    {@const isActive = value === option.value}
    <button
      type="button"
      onclick={() => select(option.value)}
      aria-pressed={isActive}
      class="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all
             {isActive
        ? 'border-accent-default bg-accent-default/10 text-accent-default ring-accent-default/20 ring-2'
        : 'border-default bg-primary text-muted hover:border-dimmer hover:text-default'}"
    >
      {#if option.value}
        <span
          class="h-2 w-2 rounded-full {getStateStyle(option.value).dotClasses}"
          aria-hidden="true"
        ></span>
      {/if}
      {option.label}
    </button>
  {/each}
</div>
