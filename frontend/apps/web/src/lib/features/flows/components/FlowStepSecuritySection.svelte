<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep, SecurityClassification } from "@eneo/eneo-js";
  import * as Select from "$lib/components/ui/select/index.js";
  import {
    getSecurityClassificationLabel,
    getSecurityInheritanceLabel,
    getSelectableSecurityClassifications
  } from "./flowStepEditHelpers";

  let {
    step,
    isPublished,
    classifications = [],
    inheritedClassification = null,
    onClassificationChange
  }: {
    step: FlowStep;
    isPublished: boolean;
    classifications?: SecurityClassification[];
    inheritedClassification?: Pick<SecurityClassification, "name" | "security_level"> | null;
    onClassificationChange?: (detail: { value: number | null }) => void;
  } = $props();

  const classificationValue = $derived(
    step.output_classification_override == null ? "" : String(step.output_classification_override)
  );
  const classificationOptions = $derived.by(() => {
    const options = [
      { value: "", label: getSecurityInheritanceLabel(inheritedClassification) },
      ...getSelectableSecurityClassifications(classifications, inheritedClassification).map(
        (classification) => ({
          value: String(classification.security_level),
          label: getSecurityClassificationLabel(classification)
        })
      )
    ];

    if (classificationValue && !options.some((option) => option.value === classificationValue)) {
      options.push({
        value: classificationValue,
        label: m.flow_step_legacy_invalid_option()
      });
    }

    return options;
  });
  const classificationLabel = $derived(
    classificationOptions.find((option) => option.value === classificationValue)?.label ??
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
          {#each classificationOptions as option (option.value)}
            <Select.Item value={option.value} label={option.label}>{option.label}</Select.Item>
          {/each}
        </Select.Group>
      </Select.Content>
    </Select.Root>
    <p class="text-muted mt-2 text-xs leading-relaxed">
      {m.flow_step_security_classification_help()}
    </p>
  </div>
</FlowStepSection>
