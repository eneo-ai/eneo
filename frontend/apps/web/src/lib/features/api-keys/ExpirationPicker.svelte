<script lang="ts">
  import {
    Calendar as CalendarIcon,
    AlertTriangle,
    Infinity as InfinityIcon,
    ChevronDown
  } from "lucide-svelte";
  import { fly } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { SvelteDate } from "svelte/reactivity";
  import { type DateValue, parseDate, today, getLocalTimeZone } from "@internationalized/date";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Calendar } from "$lib/components/ui/calendar/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";

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
  let datePopoverOpen = $state(false);

  const dateValue = $derived<DateValue | undefined>(
    customDate ? safeParseDate(customDate) : undefined
  );
  const minDateValue = $derived(today(getLocalTimeZone()).add({ days: 1 }));
  const maxDateValue = $derived(maxDays ? minDateValue.add({ days: maxDays - 1 }) : undefined);

  const locale = $derived(getLocale() === "sv" ? "sv-SE" : "en-US");

  function safeParseDate(iso: string): DateValue | undefined {
    try {
      return parseDate(iso);
    } catch {
      return undefined;
    }
  }

  function setDateFromPicker(next: DateValue | undefined) {
    if (!next) return;
    customDate = next.toString();
    datePopoverOpen = false;
  }

  function formatDateOnly(iso: string): string {
    return new Date(`${iso}T00:00:00`).toLocaleDateString(locale, {
      year: "numeric",
      month: "short",
      day: "numeric"
    });
  }

  // Preset options with their days (using getter for translations)
  const getPresets = () => [
    { label: m.api_keys_exp_7_days(), days: 7 },
    { label: m.api_keys_exp_30_days(), days: 30 },
    { label: m.api_keys_exp_90_days(), days: 90 },
    { label: m.api_keys_exp_1_year(), days: 365 }
  ];
  const presets = $derived(getPresets());

  // Filter presets based on maxDays policy
  const availablePresets = $derived(maxDays ? presets.filter((p) => p.days <= maxDays) : presets);

  // Calculate date from days offset
  function getDateFromDays(days: number): string {
    const date = new SvelteDate();
    date.setDate(date.getDate() + days);
    return date.toISOString();
  }

  // Check if a preset is selected
  function isPresetSelected(days: number): boolean {
    if (!value) return false;
    const presetDate = new Date(getDateFromDays(days));
    const selectedDate = new Date(value);
    // Compare dates (ignoring time for preset matching)
    return presetDate.toISOString().split("T")[0] === selectedDate.toISOString().split("T")[0];
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
    if (value) {
      customDate = new Date(value).toISOString().split("T")[0];
    } else {
      const defaultDate = new SvelteDate();
      defaultDate.setDate(defaultDate.getDate() + 30);
      customDate = defaultDate.toISOString().split("T")[0];
    }
  }

  // Keys expire at end-of-day local time. The worker re-checks status at
  // 01:00 UTC daily, but auth itself compares expires_at in real time —
  // 23:59:59 keeps the key usable through the chosen calendar day.
  function applyCustomDate() {
    if (!customDate) return;
    value = new Date(`${customDate}T23:59:59`).toISOString();
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
  <span id="expiration-label" class="text-default block text-sm font-medium">
    {m.api_keys_expiration()}
    {#if requireExpiration}
      <span class="text-negative-stronger">*</span>
    {/if}
  </span>

  <!-- Preset buttons -->
  <div role="group" aria-labelledby="expiration-label" class="flex flex-wrap gap-2">
    {#each availablePresets as preset (preset.days)}
      <Button
        type="button"
        variant={isPresetSelected(preset.days) ? "default" : "outline"}
        onclick={() => selectPreset(preset.days)}
        {disabled}
        aria-pressed={isPresetSelected(preset.days)}
      >
        {preset.label}
      </Button>
    {/each}

    <!-- Custom button -->
    <Button
      type="button"
      variant={showCustom ? "default" : "outline"}
      onclick={showCustomPicker}
      {disabled}
      aria-pressed={showCustom}
    >
      <CalendarIcon />
      {m.api_keys_exp_custom()}
    </Button>

    <!-- No expiration button -->
    {#if !requireExpiration}
      <Button
        type="button"
        variant={isNoExpiration ? "default" : "outline"}
        onclick={selectNoExpiration}
        {disabled}
        aria-pressed={isNoExpiration}
      >
        <InfinityIcon />
        {m.api_keys_exp_no_expiration()}
      </Button>
    {/if}
  </div>

  <!-- Custom date picker -->
  {#if showCustom}
    <div
      class="border-default bg-primary space-y-3 rounded-lg border p-4 shadow-sm"
      transition:fly={{ y: -4, duration: 150 }}
    >
      <div class="flex flex-col gap-1.5">
        <Label for="expiration-date-trigger" class="text-default text-xs font-medium">
          {m.api_keys_exp_date()}
        </Label>
        <Popover.Root bind:open={datePopoverOpen}>
          <Popover.Trigger
            id="expiration-date-trigger"
            {disabled}
            class="border-default bg-primary text-default hover:bg-subtle focus-visible:border-ring focus-visible:ring-ring/50 inline-flex h-10 w-full items-center justify-between rounded-md border px-3 text-sm transition-colors focus-visible:ring-3 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
          >
            <span class="flex items-center gap-2">
              <CalendarIcon class="text-secondary h-4 w-4" aria-hidden="true" />
              {dateValue ? formatDateOnly(customDate) : m.api_keys_exp_pick_date()}
            </span>
            <ChevronDown class="text-secondary h-4 w-4" aria-hidden="true" />
          </Popover.Trigger>
          <Popover.Content class="w-auto p-0" align="start">
            <Calendar
              type="single"
              value={dateValue}
              onValueChange={setDateFromPicker}
              minValue={minDateValue}
              maxValue={maxDateValue}
              captionLayout="dropdown"
              {locale}
            />
          </Popover.Content>
        </Popover.Root>
      </div>

      {#if maxDays}
        <p class="text-secondary flex items-center gap-1.5 text-xs">
          <AlertTriangle class="h-3.5 w-3.5" aria-hidden="true" />
          {m.api_keys_exp_max_days({ days: maxDays })}
        </p>
      {/if}
    </div>
  {/if}

  <!-- Current selection display -->
  {#if value}
    {@const daysUntil = getDaysUntil(value)}
    <div
      class="border-accent-default/30 bg-accent-default/5 flex items-center justify-between rounded-lg
             border px-4 py-3"
    >
      <div class="flex items-center gap-3">
        <div class="bg-accent-default/15 flex h-8 w-8 items-center justify-center rounded-lg">
          <CalendarIcon class="text-accent-default h-4 w-4" />
        </div>
        <div>
          <p class="text-default text-sm font-medium">
            {m.api_keys_exp_expires_on({ date: formatDisplayDate(value) })}
          </p>
          <p class="text-muted text-xs">
            {daysUntil === 1
              ? m.api_keys_exp_1_day_from_now()
              : m.api_keys_exp_days_from_now({ count: daysUntil })}
          </p>
        </div>
      </div>
    </div>
  {:else if !showCustom}
    <div
      class="border-accent-default/30 bg-accent-default/5 flex items-center gap-3 rounded-lg
             border px-4 py-3"
    >
      <div class="bg-accent-default/15 flex h-8 w-8 items-center justify-center rounded-lg">
        <InfinityIcon class="text-accent-default h-4 w-4" />
      </div>
      <div>
        <p class="text-default text-sm font-medium">{m.api_keys_exp_no_expiration()}</p>
        <p class="text-muted text-xs">{m.api_keys_exp_valid_until_revoked()}</p>
      </div>
    </div>
  {/if}

  <!-- Warning for no expiration -->
  {#if !value && !requireExpiration}
    <Alert.Root class="border-caution/30 bg-caution/5">
      <AlertTriangle class="text-caution" />
      <Alert.Description class="text-caution text-xs">
        {m.api_keys_exp_warning()}
      </Alert.Description>
    </Alert.Root>
  {/if}
</div>
