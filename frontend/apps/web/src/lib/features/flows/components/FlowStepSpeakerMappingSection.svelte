<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import type { FlowStep } from "@eneo/eneo-js";
  import { Settings } from "$lib/components/layout";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { FlowFormField } from "$lib/features/flows/flowFormSchema";
  import {
    getParticipantFieldOptions,
    getSpeakerCountFieldOptions,
    getSpeakerMappingParticipantsField,
    getSpeakerMappingSpeakerCountField
  } from "$lib/features/flows/speakerMappingConfig";

  let {
    step,
    isPublished,
    formFields = [],
    onParticipantsFieldChange,
    onSpeakerCountFieldChange
  }: {
    step: FlowStep;
    isPublished: boolean;
    formFields?: Pick<FlowFormField, "name" | "type" | "label">[];
    onParticipantsFieldChange?: (detail: { value: string | null }) => void;
    onSpeakerCountFieldChange?: (detail: { value: string | null }) => void;
  } = $props();

  const countOptions = $derived(getSpeakerCountFieldOptions(formFields));
  const countSelected = $derived(getSpeakerMappingSpeakerCountField(step));
  const countSelectedMissing = $derived(
    countSelected !== null && !countOptions.some((field) => field.name === countSelected)
  );
  const countSelectedLabel = $derived(
    countSelectedMissing
      ? m.flow_step_speaker_mapping_missing_field({ name: countSelected ?? "" })
      : (countOptions.find((field) => field.name === countSelected)?.label ??
          countSelected ??
          m.flow_step_speaker_mapping_no_count_field())
  );

  const NONE = "__none__";
  const options = $derived(getParticipantFieldOptions(formFields));
  const selected = $derived(getSpeakerMappingParticipantsField(step));
  // The configured field may have been removed from the form since.
  const selectedMissing = $derived(
    selected !== null && !options.some((field) => field.name === selected)
  );
  const selectedLabel = $derived(
    selectedMissing
      ? m.flow_step_speaker_mapping_missing_field({ name: selected ?? "" })
      : (options.find((field) => field.name === selected)?.label ??
          selected ??
          m.flow_step_speaker_mapping_no_field())
  );
</script>

<FlowStepSection title={m.flow_step_speaker_mapping_section()}>
  <Settings.Row
    title={m.flow_step_speaker_mapping_participants_field()}
    description={m.flow_step_speaker_mapping_participants_field_desc()}
    fullWidth
    density="compact"
  >
    <div class="flex flex-col gap-2">
      <Select.Root
        type="single"
        value={selected ?? NONE}
        disabled={isPublished || (options.length === 0 && selected === null)}
        onValueChange={(value) =>
          onParticipantsFieldChange?.({ value: !value || value === NONE ? null : value })}
      >
        <Select.Trigger
          class="w-full"
          aria-label={m.flow_step_speaker_mapping_participants_field()}
          aria-invalid={selected === null || selectedMissing}
        >
          {selectedLabel}
        </Select.Trigger>
        <Select.Content>
          <Select.Group>
            <Select.Item value={NONE} label={m.flow_step_speaker_mapping_no_field()}>
              {m.flow_step_speaker_mapping_no_field()}
            </Select.Item>
            {#each options as field (field.name)}
              <Select.Item value={field.name} label={field.label || field.name}>
                {field.label || field.name}
              </Select.Item>
            {/each}
          </Select.Group>
        </Select.Content>
      </Select.Root>
      <p
        class={options.length === 0 || selectedMissing
          ? "text-warning-stronger text-xs leading-relaxed"
          : "text-muted text-xs leading-relaxed"}
        aria-live="polite"
      >
        {selectedMissing
          ? m.flow_step_speaker_mapping_missing_field_help()
          : options.length === 0
            ? m.flow_step_speaker_mapping_no_usable_fields()
            : m.flow_step_speaker_mapping_help()}
      </p>
    </div>
  </Settings.Row>
  <Settings.Row
    title={m.flow_step_speaker_mapping_speaker_count_field()}
    description={m.flow_step_speaker_mapping_speaker_count_field_desc()}
    fullWidth
    density="compact"
  >
    <div class="flex flex-col gap-2">
      <Select.Root
        type="single"
        value={countSelected ?? NONE}
        disabled={isPublished || (countOptions.length === 0 && countSelected === null)}
        onValueChange={(value) =>
          onSpeakerCountFieldChange?.({ value: !value || value === NONE ? null : value })}
      >
        <Select.Trigger
          class="w-full"
          aria-label={m.flow_step_speaker_mapping_speaker_count_field()}
          aria-invalid={countSelectedMissing}
        >
          {countSelectedLabel}
        </Select.Trigger>
        <Select.Content>
          <Select.Group>
            <Select.Item value={NONE} label={m.flow_step_speaker_mapping_no_count_field()}>
              {m.flow_step_speaker_mapping_no_count_field()}
            </Select.Item>
            {#each countOptions as field (field.name)}
              <Select.Item value={field.name} label={field.label || field.name}>
                {field.label || field.name}
              </Select.Item>
            {/each}
          </Select.Group>
        </Select.Content>
      </Select.Root>
      <p
        class={countSelectedMissing
          ? "text-warning-stronger text-xs leading-relaxed"
          : "text-muted text-xs leading-relaxed"}
      >
        {countSelectedMissing
          ? m.flow_step_speaker_mapping_missing_field_help()
          : countOptions.length === 0
            ? m.flow_step_speaker_mapping_no_number_fields()
            : m.flow_step_speaker_mapping_speaker_count_help()}
      </p>
    </div>
  </Settings.Row>
</FlowStepSection>
