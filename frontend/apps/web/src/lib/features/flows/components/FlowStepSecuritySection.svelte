<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@intric/intric-js";

  let {
    step,
    isPublished,
    onClassificationChange
  }: {
    step: FlowStep;
    isPublished: boolean;
    onClassificationChange?: (detail: { value: number | null }) => void;
  } = $props();
</script>

<Settings.Group title={m.flow_step_security_classification()}>
  <div class="px-4 lg:pr-6">
    <select
      class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
      value={step.output_classification_override ?? ""}
      disabled={isPublished}
      aria-label={m.flow_step_security_classification()}
      onchange={(e) => {
        const val = e.currentTarget.value === "" ? null : Number(e.currentTarget.value);
        onClassificationChange?.({ value: val });
      }}
    >
      <option value="">{m.flow_step_security_inherit()}</option>
      <option value="1">K1</option>
      <option value="2">K2</option>
      <option value="3">K3</option>
      <option value="4">K4</option>
    </select>
  </div>
</Settings.Group>
