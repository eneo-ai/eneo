<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@eneo/eneo-js";
  import * as Select from "$lib/components/ui/select/index.js";

  let {
    step,
    isPublished,
    onClassificationChange
  }: {
    step: FlowStep;
    isPublished: boolean;
    onClassificationChange?: (detail: { value: number | null }) => void;
  } = $props();

  const CLASSIFICATION_OPTIONS = [
    { value: "", label: m.flow_step_security_inherit() },
    { value: "1", label: "K1" },
    { value: "2", label: "K2" },
    { value: "3", label: "K3" },
    { value: "4", label: "K4" }
  ];

  const classificationValue = $derived(
    step.output_classification_override == null ? "" : String(step.output_classification_override)
  );
  const classificationLabel = $derived(
    CLASSIFICATION_OPTIONS.find((o) => o.value === classificationValue)?.label ??
      classificationValue
  );
</script>

<FlowStepSection title={m.flow_step_security_classification()}>
  <div class="px-4 lg:pr-6">
    <Select.Root
      type="single"
      value={classificationValue}
      disabled={isPublished}
      onValueChange={(value) =>
        onClassificationChange?.({ value: value === "" ? null : Number(value) })}
    >
      <Select.Trigger class="w-full" aria-label={m.flow_step_security_classification()}>
        {classificationLabel}
      </Select.Trigger>
      <Select.Content>
        <Select.Group>
          {#each CLASSIFICATION_OPTIONS as option (option.value)}
            <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
          {/each}
        </Select.Group>
      </Select.Content>
    </Select.Root>
  </div>
</FlowStepSection>
