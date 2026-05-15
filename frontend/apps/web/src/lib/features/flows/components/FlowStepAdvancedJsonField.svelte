<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { Braces } from "lucide-svelte";
  import type { AdvancedJsonField } from "./advancedJsonDrafts";

  let {
    field,
    stepOrder,
    value,
    error,
    isPublished,
    placeholder,
    onUpdate,
    onFormat
  }: {
    field: AdvancedJsonField;
    stepOrder: number;
    value: string;
    error?: string;
    isPublished: boolean;
    placeholder: string;
    onUpdate?: (detail: { field: AdvancedJsonField; value: string }) => void;
    onFormat?: (detail: { field: AdvancedJsonField }) => void;
  } = $props();

  const errorId = $derived(`flow-step-${stepOrder}-${field}-error`);
  const canFormat = $derived(!isPublished && value.trim().length > 0 && !error);
  const errorMessage = $derived(error ? m.flow_step_json_parse_error() : null);
</script>

<div class="mb-2 flex justify-end">
  <Button
    variant="outline"
    size="xs"
    class="h-11 px-3 sm:h-6 sm:px-2"
    disabled={!canFormat}
    onclick={() => onFormat?.({ field })}
  >
    <Braces data-icon="inline-start" />
    {m.flow_step_json_format()}
  </Button>
</div>
<Textarea
  rows={4}
  class="bg-primary hover:border-stronger font-mono text-base shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] sm:text-sm"
  {value}
  disabled={isPublished}
  aria-invalid={Boolean(error)}
  aria-describedby={error ? errorId : undefined}
  oninput={(event) => onUpdate?.({ field, value: event.currentTarget.value })}
  {placeholder}
/>
{#if errorMessage}
  <p id={errorId} class="text-destructive mt-1 text-xs" role="status">
    {errorMessage}
  </p>
{/if}
