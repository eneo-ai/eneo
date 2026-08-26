<script lang="ts">
  import { Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { getAppContext } from "$lib/core/AppContext";

  // From the backend, so a deployment's tuned CHUNK_SIZE/CHUNK_OVERLAP is respected.
  const policy = getAppContext().settings.chunking;

  // null = "use platform default". A number = explicit override.
  export let chunkSize: number | null = null;
  export let chunkOverlap: number | null = null;

  /** max_input of the embedding model this source will use, when known. Lets the
   * input stop at the value the backend would clamp to. */
  export let maxInput: number | null | undefined = undefined;

  /** Whether this source already holds indexed material — changing the chunking
   * then costs a full re-index, so the copy becomes a warning. */
  export let hasIndexedContent: boolean = false;

  // Overlap is chosen as a share of the chunk size, so it survives a size change.
  const OVERLAP_STEP_PERCENT = 5;
  const maxOverlapPercent =
    Math.floor((policy.max_overlap_fraction * 100) / OVERLAP_STEP_PERCENT) * OVERLAP_STEP_PERCENT;

  // Start expanded only when the source already has an explicit override.
  let customize = chunkSize !== null || chunkOverlap !== null;

  // Local, always-numeric values for the inputs.
  let sizeValue = chunkSize ?? policy.default_chunk_size;
  let overlapPercent = toPercent(
    chunkOverlap ?? policy.default_chunk_overlap,
    chunkSize ?? policy.default_chunk_size
  );

  /** An overlap that does not land on one of our steps (set via the API) keeps its
   * exact token count instead of snapping; cleared when the slider is moved. */
  let exactOverlapTokens: number | null = offStepTokens(
    chunkOverlap,
    chunkSize ?? policy.default_chunk_size
  );

  /** Whether the overlap is still "use the platform default" — submitting a number
   * for an untouched field would mark the source's material stale. */
  let overlapIsDefault = chunkOverlap === null;

  /** Same for the size. Toggling the section open is disclosure, not an edit,
   * and must still submit (null, null). */
  let sizeIsDefault = chunkSize === null;

  function toPercent(tokens: number, size: number): number {
    if (size <= 0) return 0;
    const percent = Math.round((tokens / size) * 100);
    return Math.min(Math.max(percent, 0), maxOverlapPercent);
  }

  function offStepTokens(tokens: number | null, size: number): number | null {
    if (tokens === null || size <= 0) return null;
    const percent = (tokens / size) * 100;
    const onStep = Number.isInteger(percent) && percent % OVERLAP_STEP_PERCENT === 0;
    return onStep || percent > maxOverlapPercent ? null : tokens;
  }

  // Reset to the platform defaults each time the switch is turned on; initialised
  // to the current state so opening an existing override doesn't reset it.
  let wasCustomizing = customize;
  $: onCustomizeChange(customize);
  function onCustomizeChange(on: boolean) {
    if (on && !wasCustomizing) {
      sizeValue = policy.default_chunk_size;
      overlapPercent = toPercent(policy.default_chunk_overlap, policy.default_chunk_size);
      exactOverlapTokens = null;
      overlapIsDefault = true;
      sizeIsDefault = true;
    }
    wasCustomizing = on;
  }

  // The backend caps a chunk at a fraction of the embedding model's input limit;
  // an unknown limit means no cap, and inventing one here would rewrite a stored value.
  $: ceiling = maxInput ? Math.floor(maxInput * policy.max_chunk_fraction) : null;
  // Gated on the pair being explicit: an overlap-only edit submits the size too,
  // and an unclamped size would be stored lower than the editor showed. The flags
  // are read directly to avoid a reactive cycle with the reset below.
  $: if ((!sizeIsDefault || !overlapIsDefault) && ceiling !== null && sizeValue > ceiling)
    sizeValue = ceiling;
  $: sizeMax = ceiling !== null ? Math.min(ceiling, policy.max_chunk_size) : policy.max_chunk_size;

  // While the overlap is defaulted, the smallest usable size is the one where
  // that default still fits the overlap ceiling.
  $: sizeMin = overlapIsDefault
    ? Math.max(
        policy.min_chunk_size,
        Math.ceil(policy.default_chunk_overlap / policy.max_overlap_fraction)
      )
    : policy.min_chunk_size;

  // A ceiling below the absolute floor cannot carry any explicit pair, so the whole
  // customization goes back to delegation. Derived from the ceiling alone: reading
  // sizeMin here would be a reactive cycle (svelte-check).
  $: ceilingBelowFloor = ceiling !== null && ceiling < policy.min_chunk_size;
  $: if (ceilingBelowFloor && (!sizeIsDefault || !overlapIsDefault)) {
    sizeIsDefault = true;
    overlapIsDefault = true;
    sizeValue = policy.default_chunk_size;
    overlapPercent = toPercent(policy.default_chunk_overlap, policy.default_chunk_size);
    exactOverlapTokens = null;
  }

  // The range is empty only when a defaulted overlap needs a larger size than this
  // model allows; the template then promises platform defaults, so the export keeps it.
  $: rangeCollapsed = sizeMax < sizeMin;
  $: if (!sizeIsDefault && rangeCollapsed) {
    sizeIsDefault = true;
    sizeValue = policy.default_chunk_size;
  }

  // Tokens are what the API uses: floor, never above the backend's ceiling. A
  // defaulted overlap reports the platform's token default, so the number shown
  // is the number submitted.
  $: overlapTokens = overlapIsDefault
    ? policy.default_chunk_overlap
    : Math.min(
        exactOverlapTokens ?? Math.floor((sizeValue * overlapPercent) / 100),
        Math.floor(sizeValue * policy.max_overlap_fraction)
      );

  // The thumb can only sit on a step; any other value would snap, fire onInput
  // and mark the overlap explicit without anyone touching it.
  $: defaultPercentOnStep = Math.min(
    Math.round(((policy.default_chunk_overlap / sizeValue) * 100) / OVERLAP_STEP_PERCENT) *
      OVERLAP_STEP_PERCENT,
    maxOverlapPercent
  );

  // The share the tokens really represent, which can differ from the slider
  // position while an exact value is preserved.
  $: displayPercent =
    sizeValue > 0 ? Math.round((overlapTokens / sizeValue) * 100) : overlapPercent;

  // Spoken value for the slider: its own value is a percentage while the field
  // is labelled in tokens.
  $: overlapValueText = overlapIsDefault
    ? m.chunk_overlap_value_default({ tokens: overlapTokens })
    : m.chunk_overlap_value({ percent: displayPercent, tokens: overlapTokens });

  // Customisation is pair-level, matching the API: (null, null) is the only
  // delegating state, and touching either field submits both. Leaving the
  // disclosure open without touching anything still delegates; a collapsed
  // range falls back to full delegation to avoid a cycle with sizeMin.
  $: isCustomized = customize && !rangeCollapsed && (!sizeIsDefault || !overlapIsDefault);
  $: chunkSize = isCustomized ? sizeValue : null;
  $: chunkOverlap = isCustomized ? overlapTokens : null;
</script>

<Input.Switch bind:value={customize} class="border-default hover:bg-hover-dimmer p-4 px-6">
  {m.chunk_settings_customize()}
</Input.Switch>

{#if customize}
  <p class="text-secondary border-default border-b px-6 pb-3 text-sm">
    {m.chunk_settings_description()}
  </p>

  <div class="border-default flex gap-4 border-b p-4">
    <div class="flex-1" on:input={() => (sizeIsDefault = false)}>
      {#if sizeMax >= sizeMin}
        <Input.Number
          bind:value={sizeValue}
          min={sizeMin}
          max={sizeMax}
          step={10}
          labelClass="text-sm">{m.chunk_size_label()}</Input.Number
        >
        <p class="text-secondary mt-1 pl-3 text-xs">
          {m.chunk_size_description()}
          {#if ceiling}
            {m.chunk_size_ceiling_note({ ceiling })}
          {/if}
        </p>
      {:else}
        <p class="text-sm">{m.chunk_size_label()}</p>
        <p class="text-secondary mt-1 pl-3 text-xs">
          {m.chunk_size_no_valid_range({ ceiling: sizeMax })}
        </p>
      {/if}
    </div>

    <div class="flex-1">
      <p class="text-sm">{m.chunk_overlap_label()}</p>
      <div class="flex items-center gap-3 pt-3">
        <Input.Slider
          label={m.chunk_overlap_label()}
          ariaValueText={overlapValueText}
          value={overlapIsDefault ? defaultPercentOnStep : overlapPercent}
          min={0}
          max={maxOverlapPercent}
          step={OVERLAP_STEP_PERCENT}
          onInput={(next) => {
            overlapPercent = next;
            // The slider is now the source of truth for this field.
            exactOverlapTokens = null;
            overlapIsDefault = false;
          }}
        />
        <span class="text-secondary w-28 shrink-0 text-right text-xs">
          {overlapValueText}
        </span>
      </div>
      <p class="text-secondary mt-1 pl-3 text-xs">{m.chunk_overlap_description()}</p>
    </div>
  </div>

  {#if hasIndexedContent}
    <div
      class="bg-label-dimmer border-label-default text-label-stronger mx-4 my-3 rounded-md border px-3 py-2 text-sm"
      role="status"
    >
      <span class="font-medium">{m.chunk_settings_reindex_warning_title()}</span>
      {m.chunk_settings_reindex_warning()}
    </div>
  {:else}
    <div
      class="bg-info-dimmer border-info-default text-info-stronger mx-4 my-3 rounded-md border px-3 py-2 text-sm"
    >
      {m.chunk_settings_reembed_note()}
    </div>
  {/if}
{/if}
