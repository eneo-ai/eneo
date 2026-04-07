<script lang="ts">
  import { Calendar, Clock, AlertTriangle, Infinity } from "lucide-svelte";
  import { fly } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";

  let {
    value = $bindable<string | null>(null),
    maxDays = null,
    requireExpiration = false,
    disabled = false
  } = $props<{
    value?: string | null;
    maxDays?: number | null;
    requireExpiration?: boolean;
    disabled?: boolean;
  }>();

  let showCustom = $state(false);
  let customDate = $state("");
  let customTime = $state("23:59");

  // Preset options with their days (using getter for translations)
  const getPresets = () => [
    { label: m.api_keys_exp_7_days(), days: 7 },
    { label: m.api_keys_exp_30_days(), days: 30 },
    { label: m.api_keys_exp_90_days(), days: 90 },
    { label: m.api_keys_exp_1_year(), days: 365 }
  ];
  const presets = $derived(getPresets());

  // Filter presets based on maxDays policy
  const availablePresets = $derived(
    maxDays ? presets.filter((p) => p.days <= maxDays) : presets
  );

  // Calculate date from days offset
  function getDateFromDays(days: number): string {
    const date = new Date();
    date.setDate(date.getDate() + days);
    return date.toISOString();
  }

  // Get minimum date for custom picker (tomorrow)
  const minDate = $derived(() => {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    return tomorrow.toISOString().split("T")[0];
  });

  // Get maximum date for custom picker
  const maxDate = $derived(() => {
    if (!maxDays) return null;
    const max = new Date();
    max.setDate(max.getDate() + maxDays);
    return max.toISOString().split("T")[0];
  });

  // Check if a preset is selected
  function isPresetSelected(days: number): boolean {
    if (!value) return false;
    const presetDate = new Date(getDateFromDays(days));
    const selectedDate = new Date(value);
    // Compare dates (ignoring time for preset matching)
    return (
      presetDate.toISOString().split("T")[0] === selectedDate.toISOString().split("T")[0]
    );
  }

  // Check if "No expiration" is selected
  const isNoExpiration = $derived(value === null && !showCustom);

  // Select a preset
  function selectPreset(days: number) {
    value = getDateFromDays(days);
    showCustom = false;
    customDate = "";
  }

  // Select no expiration
  function selectNoExpiration() {
    if (requireExpiration) return;
    value = null;
    showCustom = false;
    customDate = "";
  }

  // Show custom date picker
  function showCustomPicker() {
    showCustom = true;
    // Initialize with current value or a sensible default
    if (value) {
      const date = new Date(value);
      customDate = date.toISOString().split("T")[0];
      customTime = date.toTimeString().slice(0, 5);
    } else {
      // Default to 30 days from now
      const defaultDate = new Date();
      defaultDate.setDate(defaultDate.getDate() + 30);
      customDate = defaultDate.toISOString().split("T")[0];
      customTime = "23:59";
    }
  }

  // Apply custom date
  function applyCustomDate() {
    if (!customDate) return;
    const dateTime = new Date(`${customDate}T${customTime}:00`);
    value = dateTime.toISOString();
  }

  // Format display date
  function formatDisplayDate(isoString: string): string {
    const date = new Date(isoString);
    const locale = getLocale();
    return date.toLocaleDateString(locale === "sv" ? "sv-SE" : "en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  // Calculate days until expiration
  function getDaysUntil(isoString: string): number {
    const now = new Date();
    const target = new Date(isoString);
    return Math.ceil((target.getTime() - now.getTime()) / (1000 * 60 * 60 * 24));
  }

  // Effect to apply custom date changes
  $effect(() => {
    if (showCustom && customDate) {
      applyCustomDate();
    }
  });
</script>

<div class="space-y-3">
  <span id="expiration-label" class="block text-sm font-medium text-default">
    {m.api_keys_expiration()}
    {#if requireExpiration}
      <span class="text-negative">*</span>
    {/if}
  </span>

  <!-- Preset buttons -->
  <div role="group" aria-labelledby="expiration-label" class="flex flex-wrap gap-2">
    {#each availablePresets as preset}
      <button
        type="button"
        onclick={() => selectPreset(preset.days)}
        disabled={disabled}
        class="rounded-lg border px-4 py-2 text-sm font-medium transition-all duration-150
               {isPresetSelected(preset.days)
          ? 'border-accent-default bg-accent-default/10 text-accent-default ring-2 ring-accent-default/20'
          : 'border-default bg-primary text-default hover:border-dimmer hover:bg-subtle'}
               disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {preset.label}
      </button>
    {/each}

    <!-- Custom button -->
    <button
      type="button"
      onclick={showCustomPicker}
      disabled={disabled}
      class="rounded-lg border px-4 py-2 text-sm font-medium transition-all duration-150
             flex items-center gap-2
             {showCustom
        ? 'border-accent-default bg-accent-default/10 text-accent-default ring-2 ring-accent-default/20'
        : 'border-default bg-primary text-default hover:border-dimmer hover:bg-subtle'}
             disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <Calendar class="h-4 w-4" />
      {m.api_keys_exp_custom()}
    </button>

    <!-- No expiration button -->
    {#if !requireExpiration}
      <button
        type="button"
        onclick={selectNoExpiration}
        disabled={disabled}
        class="rounded-lg border px-4 py-2 text-sm font-medium transition-all duration-150
               flex items-center gap-2
               {isNoExpiration
          ? 'border-accent-default bg-accent-default/10 text-accent-default ring-2 ring-accent-default/20'
          : 'border-default bg-primary text-default hover:border-dimmer hover:bg-subtle'}
               disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <Infinity class="h-4 w-4" />
        {m.api_keys_exp_no_expiration()}
      </button>
    {/if}
  </div>

  <!-- Custom date picker -->
  {#if showCustom}
    <div
      class="rounded-lg border border-default bg-subtle p-4 space-y-3"
      transition:fly={{ y: -4, duration: 150 }}
    >
      <div class="grid gap-3 sm:grid-cols-2">
        <div>
          <label for="expiration-date" class="mb-1.5 block text-xs font-medium text-muted">{m.api_keys_exp_date()}</label>
          <input
            id="expiration-date"
            type="date"
            bind:value={customDate}
            min={minDate()}
            max={maxDate()}
            disabled={disabled}
            class="h-10 w-full rounded-lg border border-default bg-primary px-3 text-sm
                   focus:border-accent-default focus:ring-2 focus:ring-accent-default/20
                   disabled:opacity-50 disabled:cursor-not-allowed"
          />
        </div>
        <div>
          <label for="expiration-time" class="mb-1.5 block text-xs font-medium text-muted">{m.api_keys_exp_time()}</label>
          <div class="relative">
            <Clock class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted pointer-events-none" />
            <input
              id="expiration-time"
              type="time"
              bind:value={customTime}
              disabled={disabled}
              class="h-10 w-full rounded-lg border border-default bg-primary pl-10 pr-3 text-sm
                     focus:border-accent-default focus:ring-2 focus:ring-accent-default/20
                     disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>
        </div>
      </div>

      {#if maxDays}
        <p class="text-xs text-muted flex items-center gap-1.5">
          <AlertTriangle class="h-3.5 w-3.5" />
          {m.api_keys_exp_max_days({ days: maxDays })}
        </p>
      {/if}
    </div>
  {/if}

  <!-- Current selection display -->
  {#if value}
    {@const daysUntil = getDaysUntil(value)}
    <div
      class="rounded-lg border border-accent-default/30 bg-accent-default/5 px-4 py-3
             flex items-center justify-between"
    >
      <div class="flex items-center gap-3">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-default/15">
          <Calendar class="h-4 w-4 text-accent-default" />
        </div>
        <div>
          <p class="text-sm font-medium text-default">
            {m.api_keys_exp_expires_on({ date: formatDisplayDate(value) })}
          </p>
          <p class="text-xs text-muted">
            {daysUntil === 1 ? m.api_keys_exp_1_day_from_now() : m.api_keys_exp_days_from_now({ count: daysUntil })}
          </p>
        </div>
      </div>
    </div>
  {:else if !showCustom}
    <div
      class="rounded-lg border border-accent-default/30 bg-accent-default/5 px-4 py-3
             flex items-center gap-3"
    >
      <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-default/15">
        <Infinity class="h-4 w-4 text-accent-default" />
      </div>
      <div>
        <p class="text-sm font-medium text-default">{m.api_keys_exp_no_expiration()}</p>
        <p class="text-xs text-muted">{m.api_keys_exp_valid_until_revoked()}</p>
      </div>
    </div>
  {/if}

  <!-- Warning for no expiration -->
  {#if !value && !requireExpiration}
    <div class="flex items-start gap-2.5 rounded-lg border border-caution/20 bg-caution/5 px-3 py-2.5 text-xs text-caution">
      <AlertTriangle class="h-4 w-4 flex-shrink-0" />
      <span>{m.api_keys_exp_warning()}</span>
    </div>
  {/if}
</div>
