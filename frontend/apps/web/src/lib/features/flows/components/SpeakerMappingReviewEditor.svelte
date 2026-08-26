<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import { SvelteSet } from "svelte/reactivity";
  import type { SpeakerMappingRow } from "$lib/features/flows/speakerMappingReview";

  const NONE = "__none__";
  const OTHER = "__other__";

  let {
    rows,
    participants,
    disabled = false,
    onChange
  }: {
    rows: SpeakerMappingRow[];
    participants: string[];
    disabled?: boolean;
    onChange: (rows: SpeakerMappingRow[]) => void;
  } = $props();

  // Rows whose name is not a participant use the free-text input; a reviewer
  // who picked "someone else" but has not typed yet is tracked separately.
  const forcedOther = new SvelteSet<string>();
  // Names typed for one speaker are offered to the others: diarization often
  // splits one person into several labels.
  const knownNames = $derived.by(() => {
    const names = [...participants];
    for (const row of rows) {
      const name = row.name?.trim();
      if (name && !names.includes(name)) names.push(name);
    }
    return names;
  });
  const customLabels = $derived(
    new Set(
      rows
        .filter(
          (row) =>
            forcedOther.has(row.label) || (row.name !== null && !knownNames.includes(row.name))
        )
        .map((row) => row.label)
    )
  );

  function selectValue(row: SpeakerMappingRow): string {
    if (customLabels.has(row.label)) return OTHER;
    return row.name ?? NONE;
  }

  function selectLabel(row: SpeakerMappingRow): string {
    const value = selectValue(row);
    if (value === OTHER) return m.flow_run_review_speakers_other();
    if (value === NONE) return m.flow_run_review_speakers_unassigned();
    return value;
  }

  function update(label: string, patch: Partial<SpeakerMappingRow>) {
    onChange(rows.map((row) => (row.label === label ? { ...row, ...patch } : row)));
  }

  function onSelect(row: SpeakerMappingRow, value: string | undefined) {
    if (value === OTHER) {
      forcedOther.add(row.label);
      update(row.label, { name: knownNames.includes(row.name ?? "") ? "" : row.name });
      return;
    }
    forcedOther.delete(row.label);
    update(row.label, { name: value === NONE || !value ? null : value });
  }

  function confidenceText(confidence: SpeakerMappingRow["confidence"]): string {
    if (confidence === "high") return m.flow_run_review_speakers_confidence_high();
    if (confidence === "medium") return m.flow_run_review_speakers_confidence_medium();
    return m.flow_run_review_speakers_confidence_low();
  }
</script>

<div class="flex flex-col gap-3">
  <div>
    <h4 class="text-primary text-sm font-semibold">{m.flow_run_review_speakers_title()}</h4>
    <p class="text-muted mt-1 text-xs leading-relaxed">{m.flow_run_review_speakers_help()}</p>
  </div>
  {#each rows as row (row.label)}
    <div class="border-default bg-primary flex flex-col gap-3 rounded-lg border p-3">
      <div class="flex flex-wrap items-center gap-2">
        <Badge variant="secondary" class="font-mono">{row.label}</Badge>
        <span class="text-muted text-xs">
          {m.flow_run_review_speakers_lines({ count: String(row.lineCount) })}
        </span>
        <Badge variant="outline" class="ml-auto text-xs">{confidenceText(row.confidence)}</Badge>
      </div>
      {#if row.samples.length > 0}
        <ul class="text-secondary flex flex-col gap-1 text-xs leading-relaxed">
          {#each row.samples as sample, index (index)}
            <li class="truncate italic">“{sample}”</li>
          {/each}
        </ul>
      {/if}
      <div class="grid gap-2 sm:grid-cols-2">
        <Select.Root
          type="single"
          value={selectValue(row)}
          {disabled}
          onValueChange={(value) => onSelect(row, value)}
        >
          <Select.Trigger class="w-full" aria-label={row.label}>
            {selectLabel(row)}
          </Select.Trigger>
          <Select.Content>
            <Select.Group>
              {#each knownNames as name (name)}
                <Select.Item value={name} label={name}>{name}</Select.Item>
              {/each}
              <Select.Item value={OTHER} label={m.flow_run_review_speakers_other()}>
                {m.flow_run_review_speakers_other()}
              </Select.Item>
              <Select.Item value={NONE} label={m.flow_run_review_speakers_unassigned()}>
                {m.flow_run_review_speakers_unassigned()}
              </Select.Item>
            </Select.Group>
          </Select.Content>
        </Select.Root>
        {#if customLabels.has(row.label)}
          <Input
            value={row.name ?? ""}
            {disabled}
            placeholder={m.flow_run_review_speakers_other_placeholder()}
            aria-label={m.flow_run_review_speakers_other_placeholder()}
            oninput={(event) => {
              forcedOther.add(row.label);
              update(row.label, { name: event.currentTarget.value });
            }}
          />
        {/if}
      </div>
      {#if row.evidence}
        <p class="text-muted text-xs leading-relaxed">
          <span class="font-medium">{m.flow_run_review_speakers_evidence()}:</span>
          {row.evidence}
        </p>
      {/if}
    </div>
  {/each}
</div>
