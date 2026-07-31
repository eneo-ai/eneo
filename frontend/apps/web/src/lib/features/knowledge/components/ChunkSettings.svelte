<script lang="ts">
  import { Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { getAppContext } from "$lib/core/AppContext";

  // The platform policy comes from the backend. Hardcoding it here would silently
  // override a deployment that tunes CHUNK_SIZE, CHUNK_OVERLAP or either ceiling.
  const policy = getAppContext().settings.chunking;

  // null = "use platform default". A number = explicit override.
  export let chunkSize: number | null = null;
  export let chunkOverlap: number | null = null;

  /** max_input of the embedding model this source will use, when known. Lets the
   * input stop at the value the backend would clamp to instead of silently lowering
   * it after the fact. */
  export let maxInput: number | null | undefined = undefined;

  // Overlap is chosen as a share of the chunk size, which is how the limit is defined
  // and how the practical guidance is stated, and it survives a change of chunk size:
  // an absolute overlap would quietly slide from 20% to 4% when the size grows.
  const OVERLAP_STEP_PERCENT = 5;
  // Input.Number falls back to its own default when max is undefined, so "no limit"
  // has to be an explicit bound rather than an omitted prop.
  const NO_SIZE_LIMIT = Number.MAX_SAFE_INTEGER;
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

  /** An overlap that does not land on one of our steps — a value set through the API,
   * or a deployment default whose ratio is not a whole step — keeps its exact token
   * count instead of snapping, so the value shown never disagrees with the value
   * indexed. Cleared only when the user moves the slider. */
  let exactOverlapTokens: number | null = offStepTokens(
    chunkOverlap ?? policy.default_chunk_overlap,
    chunkSize ?? policy.default_chunk_size
  );

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

  // Reset to the platform defaults each time the switch is turned on, so toggling off
  // then on always starts from the deployment's values. Initialised to the current
  // state so opening an existing override doesn't reset it.
  let wasCustomizing = customize;
  $: onCustomizeChange(customize);
  function onCustomizeChange(on: boolean) {
    if (on && !wasCustomizing) {
      sizeValue = policy.default_chunk_size;
      overlapPercent = toPercent(policy.default_chunk_overlap, policy.default_chunk_size);
      // Keep the deployment's exact default rather than a value rebuilt from a
      // rounded percentage — enabling the switch must not move the other control.
      exactOverlapTokens = offStepTokens(policy.default_chunk_overlap, policy.default_chunk_size);
    }
    wasCustomizing = on;
  }

  // The backend caps a chunk at a fraction of the embedding model's input limit. When
  // that limit is unknown the backend accepts any size, so this must not invent a cap
  // of its own — doing so would rewrite a stored value the administrator never edited.
  $: ceiling = maxInput ? Math.floor(maxInput * policy.max_chunk_fraction) : null;
  $: if (ceiling !== null && sizeValue > ceiling) sizeValue = ceiling;

  // Tokens are what the API and the index actually use. Floor, and never above the
  // backend's own integer ceiling — rounding up would offer a pair the API refuses.
  $: overlapTokens = Math.min(
    exactOverlapTokens ?? Math.floor((sizeValue * overlapPercent) / 100),
    Math.floor(sizeValue * policy.max_overlap_fraction)
  );

  // Report the share the tokens really represent, which can differ from the slider
  // position while an exact value is being preserved.
  $: displayPercent =
    sizeValue > 0 ? Math.round((overlapTokens / sizeValue) * 100) : overlapPercent;

  // Derive the nullable props: null when off (use defaults), the value when on.
  $: chunkSize = customize ? sizeValue : null;
  $: chunkOverlap = customize ? overlapTokens : null;
</script>

<Input.Switch bind:value={customize} class="border-default hover:bg-hover-dimmer p-4 px-6">
  {m.chunk_settings_customize()}
</Input.Switch>

{#if customize}
  <p class="text-secondary border-default border-b px-6 pb-3 text-sm">
    {m.chunk_settings_description()}
  </p>

  <div class="border-default flex gap-4 border-b p-4">
    <div class="flex-1">
      <Input.Number
        bind:value={sizeValue}
        min={policy.min_chunk_size}
        max={ceiling ?? NO_SIZE_LIMIT}
        step={10}
        labelClass="text-sm">{m.chunk_size_label()}</Input.Number
      >
      <p class="text-secondary mt-1 pl-3 text-xs">
        {m.chunk_size_description()}
        {#if ceiling}
          {m.chunk_size_ceiling_note({ ceiling })}
        {/if}
      </p>
    </div>

    <div class="flex-1">
      <p class="text-sm">{m.chunk_overlap_label()}</p>
      <div class="flex items-center gap-3 pt-3">
        <Input.Slider
          value={overlapPercent}
          min={0}
          max={maxOverlapPercent}
          step={OVERLAP_STEP_PERCENT}
          onInput={(next) => {
            overlapPercent = next;
            // The slider is now the source of truth for this field.
            exactOverlapTokens = null;
          }}
        />
        <span class="text-secondary w-28 shrink-0 text-right text-xs">
          {m.chunk_overlap_value({ percent: displayPercent, tokens: overlapTokens })}
        </span>
      </div>
      <p class="text-secondary mt-1 pl-3 text-xs">{m.chunk_overlap_description()}</p>
    </div>
  </div>

  <div
    class="bg-info-dimmer border-info-default text-info-stronger mx-4 my-3 rounded-md border px-3 py-2 text-sm"
  >
    {m.chunk_settings_reembed_note()}
  </div>
{/if}
