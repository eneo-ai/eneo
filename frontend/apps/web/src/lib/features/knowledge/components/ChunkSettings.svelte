<script lang="ts">
  import { Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { getAppContext } from "$lib/core/AppContext";

  // The platform policy comes from the backend. Hardcoding it here would silently
  // override a deployment that tunes CHUNK_SIZE, CHUNK_OVERLAP or the ceiling.
  const policy = getAppContext().settings.chunking;

  // null = "use platform default". A number = explicit override.
  export let chunkSize: number | null = null;
  export let chunkOverlap: number | null = null;

  /** max_input of the embedding model this source will use, when known. Lets the
   * inputs stop at the value the backend would clamp to instead of silently
   * lowering it after the fact. */
  export let maxInput: number | null | undefined = undefined;

  // Start expanded only when the source already has an explicit override.
  let customize = chunkSize !== null || chunkOverlap !== null;

  // Local, always-numeric values for the inputs (Input.Number requires a number).
  let sizeValue = chunkSize ?? policy.default_chunk_size;
  let overlapValue = chunkOverlap ?? policy.default_chunk_overlap;

  // Reset the inputs to the platform defaults each time the switch is turned on,
  // so toggling off then on always starts fresh from the deployment's values.
  // Initialised to the current state so opening an existing override doesn't reset.
  let wasCustomizing = customize;
  $: onCustomizeChange(customize);
  function onCustomizeChange(on: boolean) {
    if (on && !wasCustomizing) {
      sizeValue = policy.default_chunk_size;
      overlapValue = policy.default_chunk_overlap;
    }
    wasCustomizing = on;
  }

  // Derive the nullable props: null when off (use defaults), the input value when on.
  $: chunkSize = customize ? sizeValue : null;
  $: chunkOverlap = customize ? overlapValue : null;

  // The backend caps a chunk at a fraction of the embedding model's input limit.
  $: ceiling = maxInput ? Math.floor(maxInput * policy.max_chunk_fraction) : null;
  $: sizeMax = ceiling ?? 4000;
  $: if (sizeValue > sizeMax) sizeValue = sizeMax;

  // The platform refuses an overlap above a share of the chunk size, so the input
  // stops there instead of letting the request fail on submit.
  $: overlapMax = Math.floor(sizeValue * policy.max_overlap_fraction);
  $: if (overlapValue > overlapMax) overlapValue = overlapMax;
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
      <Input.Number bind:value={sizeValue} min={1} max={sizeMax} step={10} labelClass="text-sm"
        >{m.chunk_size_label()}</Input.Number
      >
      <p class="text-secondary mt-1 pl-3 text-xs">
        {m.chunk_size_description()}
        {#if ceiling}
          {m.chunk_size_ceiling_note({ ceiling })}
        {/if}
      </p>
    </div>

    <div class="flex-1">
      <Input.Number bind:value={overlapValue} min={0} max={overlapMax} step={5} labelClass="text-sm"
        >{m.chunk_overlap_label()}</Input.Number
      >
      <p class="text-secondary mt-1 pl-3 text-xs">{m.chunk_overlap_description()}</p>
    </div>
  </div>

  <div
    class="bg-info-dimmer border-info-default text-info-stronger mx-4 my-3 rounded-md border px-3 py-2 text-sm"
  >
    {m.chunk_settings_reembed_note()}
  </div>
{/if}
