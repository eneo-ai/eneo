<script lang="ts">
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";

  type ByteUnit = "B" | "KB" | "MB" | "GB";

  type Props = {
    id: string;
    label: string;
    description: string;
    bytes: number;
    storedBytes: number;
    disabled: boolean;
  };

  const unitBytes: Record<ByteUnit, number> = {
    B: 1,
    KB: 1024,
    MB: 1024 ** 2,
    GB: 1024 ** 3
  };
  const units: ByteUnit[] = ["B", "KB", "MB", "GB"];

  let { id, label, description, bytes = $bindable(), storedBytes, disabled }: Props = $props();
  let unit = $derived<ByteUnit>(unitFor(storedBytes));
  const value = $derived(bytes / unitBytes[unit]);
  const valid = $derived(Number.isSafeInteger(bytes) && bytes > 0);

  function unitFor(value: number): ByteUnit {
    for (const candidate of ["GB", "MB", "KB"] as const) {
      if (value % unitBytes[candidate] === 0) return candidate;
    }
    return "B";
  }

  function updateValue(next: number | string | undefined): void {
    bytes = Number(next) * unitBytes[unit];
  }

  function updateUnit(next: string): void {
    if (next === "B" || next === "KB" || next === "MB" || next === "GB") unit = next;
  }

  function unitLabel(value: ByteUnit): string {
    const labels: Record<ByteUnit, () => string> = {
      B: m.storage_unit_b,
      KB: m.storage_unit_kb,
      MB: m.storage_unit_mb,
      GB: m.storage_unit_gb
    };
    return labels[value]();
  }
</script>

<Field.Field data-invalid={!valid || undefined}>
  <Field.Label for={id}>{label}</Field.Label>
  <div class="grid grid-cols-[minmax(0,1fr)_6.5rem] gap-2">
    <Input
      {id}
      type="number"
      min="0"
      step="any"
      required
      {disabled}
      aria-invalid={!valid}
      aria-describedby={`${id}-description`}
      bind:value={() => value, updateValue}
    />
    <Select.Root type="single" bind:value={() => unit, updateUnit} {disabled}>
      <Select.Trigger
        aria-label={m.storage_limit_unit({ limit: label })}
        aria-describedby={`${id}-description`}
        aria-invalid={!valid}
        class="w-full"
      >
        <span data-slot="select-value">{unitLabel(unit)}</span>
      </Select.Trigger>
      <Select.Content>
        <Select.Group>
          {#each units as candidate (candidate)}
            <Select.Item value={candidate} label={unitLabel(candidate)}>
              {unitLabel(candidate)}
            </Select.Item>
          {/each}
        </Select.Group>
      </Select.Content>
    </Select.Root>
  </div>
  <Field.Description id={`${id}-description`}>{description}</Field.Description>
</Field.Field>
