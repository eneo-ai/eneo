<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { m } from "$lib/paraglide/messages";
  import IconX from "lucide-svelte/icons/x";

  let {
    id,
    values,
    required = false,
    invalid = false,
    describedBy,
    placeholder = m.flow_list_input_placeholder(),
    onchange
  }: {
    id: string;
    values: string[];
    required?: boolean;
    invalid?: boolean;
    describedBy?: string;
    placeholder?: string;
    onchange: (values: string[]) => void;
  } = $props();

  let draft = $state("");

  function splitEntries(text: string): string[] {
    return text
      .split(/[\n,;]+/)
      .map((entry) => entry.trim())
      .filter((entry) => entry.length > 0);
  }

  function addEntries(text: string): void {
    const next = [...values];
    for (const entry of splitEntries(text)) {
      if (!next.some((existing) => existing.toLowerCase() === entry.toLowerCase())) {
        next.push(entry);
      }
    }
    draft = "";
    if (next.length !== values.length) onchange(next);
  }

  function removeAt(index: number): void {
    onchange(values.filter((_, i) => i !== index));
  }

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === "Enter" || event.key === ",") {
      if (draft.trim().length === 0) {
        if (event.key === "Enter") event.preventDefault();
        return;
      }
      event.preventDefault();
      addEntries(draft);
    } else if (event.key === "Backspace" && draft.length === 0 && values.length > 0) {
      event.preventDefault();
      removeAt(values.length - 1);
    }
  }

  function onpaste(event: ClipboardEvent): void {
    const text = event.clipboardData?.getData("text") ?? "";
    if (splitEntries(text).length > 1) {
      event.preventDefault();
      addEntries(text);
    }
  }
</script>

<div class="flex flex-col gap-2">
  {#if values.length > 0}
    <ul class="flex flex-wrap gap-1.5" aria-label={m.flow_list_input_entries()}>
      {#each values as value, index (value)}
        <li>
          <Badge variant="secondary" class="h-6 gap-1 pr-1">
            <span class="max-w-[16rem] truncate">{value}</span>
            <button
              type="button"
              class="hover:bg-hover-dimmer inline-flex size-4 items-center justify-center rounded-full"
              aria-label={m.flow_list_input_remove({ value })}
              onclick={() => removeAt(index)}
            >
              <IconX class="size-3" />
            </button>
          </Badge>
        </li>
      {/each}
    </ul>
  {/if}
  <Input
    {id}
    type="text"
    bind:value={draft}
    {placeholder}
    autocomplete="off"
    aria-required={required}
    aria-invalid={invalid}
    aria-describedby={describedBy}
    {onkeydown}
    {onpaste}
    onblur={() => {
      if (draft.trim().length > 0) addEntries(draft);
    }}
  />
</div>
