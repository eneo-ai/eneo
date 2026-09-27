<script lang="ts">
  import { useId } from "bits-ui";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import Row from "./Row.svelte";
  import InfoTip from "./InfoTip.svelte";
  import type { ToggleField } from "./form.svelte";

  let {
    title,
    description = "",
    label,
    field,
    info = undefined
  }: {
    title: string;
    description?: string;
    /** Visible label next to the switch. */
    label: string;
    field: ToggleField;
    info?: string;
  } = $props();

  const switchId = useId();
</script>

<Row
  {title}
  {description}
  hasChanges={field.dirty}
  revertFn={() => field.reset()}
  let:descriptionId
>
  <svelte:fragment slot="title">
    {#if info}<InfoTip {title} text={info} />{/if}
  </svelte:fragment>
  <div class="flex items-center gap-3 pt-1">
    <Switch id={switchId} bind:checked={field.value} aria-describedby={descriptionId} />
    <Label for={switchId} class="text-primary font-normal">{label}</Label>
  </div>
</Row>
