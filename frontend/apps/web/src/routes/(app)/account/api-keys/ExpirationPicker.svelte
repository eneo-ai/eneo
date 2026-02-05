<script lang="ts">
  import { Calendar, Clock, AlertTriangle, Infinity } from "lucide-svelte";
  import { fly } from "svelte/transition";

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

  // Preset options with their days
  const presets = [
    { label: "7 days", days: 7 },
    { label: "30 days", days: 30 },
    { label: "90 days", days: 90 },
    { label: "1 year", days: 365 }
  ];

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
    return date.toLocaleDateString("sv-SE", {
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
  <label class="block text-sm font-medium text-default">
    Expiration
    {#if requireExpiration}
      <span class="text-negative">*</span>
    {/if}
  </label>

  <!-- Preset buttons -->
  <div class="flex flex-wrap gap-2">
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
      Custom
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
        No expiration
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
          <label class="mb-1.5 block text-xs font-medium text-muted">Date</label>
          <input
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
          <label class="mb-1.5 block text-xs font-medium text-muted">Time</label>
          <div class="relative">
            <Clock class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted pointer-events-none" />
            <input
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
          Maximum allowed: {maxDays} days from now
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
            Expires {formatDisplayDate(value)}
          </p>
          <p class="text-xs text-muted">
            {daysUntil === 1 ? "1 day" : `${daysUntil} days`} from now
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
        <p class="text-sm font-medium text-default">No expiration</p>
        <p class="text-xs text-muted">This key will remain valid until manually revoked</p>
      </div>
    </div>
  {/if}

  <!-- Warning for no expiration -->
  {#if !value && !requireExpiration}
    <div class="flex items-start gap-2.5 rounded-lg border border-caution/20 bg-caution/5 px-3 py-2.5 text-xs text-caution">
      <AlertTriangle class="h-4 w-4 flex-shrink-0" />
      <span>Keys without expiration pose a security risk. Consider setting an expiration date.</span>
    </div>
  {/if}
</div>
