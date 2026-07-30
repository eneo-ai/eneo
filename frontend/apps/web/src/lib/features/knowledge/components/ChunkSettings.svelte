<script lang="ts">
  import { Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";

  // Platform defaults — mirror backend ChunkSettings (chunk_size=200, chunk_overlap=40).
  const DEFAULT_CHUNK_SIZE = 200;
  const DEFAULT_CHUNK_OVERLAP = 40;

  // null = "use platform default". A number = explicit override.
  export let chunkSize: number | null = null;
  export let chunkOverlap: number | null = null;

  // Start expanded only when the source already has an explicit override.
  let customize = chunkSize !== null || chunkOverlap !== null;

  // Local, always-numeric values for the inputs (Input.Number requires a number).
  let sizeValue = chunkSize ?? DEFAULT_CHUNK_SIZE;
  let overlapValue = chunkOverlap ?? DEFAULT_CHUNK_OVERLAP;

  // Reset the inputs to the platform defaults each time the switch is turned on,
  // so toggling off then on always starts fresh from 200/40 (not the last values).
  // Initialised to the current state so opening an existing override doesn't reset.
  let wasCustomizing = customize;
  $: onCustomizeChange(customize);
  function onCustomizeChange(on: boolean) {
    if (on && !wasCustomizing) {
      sizeValue = DEFAULT_CHUNK_SIZE;
      overlapValue = DEFAULT_CHUNK_OVERLAP;
    }
    wasCustomizing = on;
  }

  // Derive the nullable props: null when off (use defaults), the input value when on.
  $: chunkSize = customize ? sizeValue : null;
  $: chunkOverlap = customize ? overlapValue : null;

  // Overlap can never exceed the chunk size (backend caps it at size / 2).
  $: if (overlapValue > sizeValue) overlapValue = sizeValue;
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
      <Input.Number bind:value={sizeValue} min={1} max={4000} step={10} labelClass="text-sm"
        >{m.chunk_size_label()}</Input.Number
      >
      <p class="text-secondary mt-1 pl-3 text-xs">{m.chunk_size_description()}</p>
    </div>

    <div class="flex-1">
      <Input.Number bind:value={overlapValue} min={0} max={sizeValue} step={5} labelClass="text-sm"
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
