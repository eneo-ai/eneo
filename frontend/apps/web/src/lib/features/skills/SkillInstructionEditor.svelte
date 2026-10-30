<script lang="ts">
  import { onMount } from "svelte";
  import { parseInstructionReferences, type ReferenceCatalog } from "@eneo/skill-instructions";
  import {
    createInstructionEditor,
    type InstructionEditor,
    type ReferenceSelection
  } from "@eneo/skill-instructions/editor";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import AtSign from "@lucide/svelte/icons/at-sign";
  import Code from "@lucide/svelte/icons/code";
  import { m } from "$lib/paraglide/messages";
  import SkillReferencePicker from "./SkillReferencePicker.svelte";
  import "@eneo/skill-instructions/editor.css";

  let {
    value = $bindable(),
    id,
    describedBy = "",
    disabled,
    invalid,
    catalog,
    inlinePicker = false
  }: {
    value: string;
    id: string;
    describedBy?: string;
    disabled: boolean;
    invalid: boolean;
    catalog: ReferenceCatalog;
    inlinePicker?: boolean;
  } = $props();
  let mount: HTMLDivElement;
  let editor = $state.raw<InstructionEditor | null>(null);
  let source = $state(false);
  let selection = $state<ReferenceSelection | null>(null);
  let announcement = $state("");
  const malformed = $derived.by(() => {
    try {
      parseInstructionReferences(value);
      return false;
    } catch {
      return true;
    }
  });

  onMount(() => {
    editor = createInstructionEditor({
      element: mount,
      value,
      id,
      label: m.skills_instructions_label(),
      placeholder: m.skills_reference_placeholder(),
      describedBy: `${id}-reference-hint ${id}-reference-error ${describedBy}`.trim(),
      referenceTypeLabels: {
        skill: m.skills_reference_kind_skill(),
        function: m.skills_reference_kind_function(),
        mcp_server: m.skills_reference_kind_mcp(),
        mcp_tool: m.skills_reference_kind_tool()
      },
      editorClass:
        "text-foreground relative min-h-48 max-h-[50dvh] w-full overflow-y-auto px-3 py-3 text-base sm:text-sm leading-7 whitespace-pre-wrap wrap-anywhere outline-none [--skill-placeholder:var(--text-secondary)] [&>p]:m-0",
      referenceClass:
        "bg-accent-dimmer text-accent-stronger mx-0.5 cursor-pointer rounded-md border-0 px-1.5 py-0.5 text-sm font-medium leading-normal hover:underline underline-offset-2 [&.ProseMirror-selectednode]:outline-2 [&.ProseMirror-selectednode]:outline-accent-stronger",
      onChange: (text) => {
        value = text;
      },
      onReference: (next) => {
        selection = next;
      }
    });
    return () => editor?.destroy();
  });
  $effect(() => editor?.setValue(value));
  $effect(() => editor?.setState({ disabled, invalid: invalid || malformed }));
  export function focus() {
    editor?.focus();
  }
  function closePicker() {
    selection = null;
    requestAnimationFrame(() => editor?.focus());
  }
</script>

<div class="flex min-w-0 flex-col gap-2">
  <InputGroup.Root>
    <div bind:this={mount} class="w-full min-w-0"></div>
    <InputGroup.Addon
      align="block-end"
      class="text-foreground flex-wrap justify-between gap-2 border-t"
    >
      <InputGroup.Button size="sm" {disabled} onclick={() => editor?.openReference()}
        ><AtSign data-icon="inline-start" />{m.skills_reference_insert()}</InputGroup.Button
      >
      <InputGroup.Button
        size="sm"
        {disabled}
        aria-pressed={source}
        onclick={() => {
          source = !source;
          editor?.setSource(source);
        }}
        ><Code data-icon="inline-start" />{source
          ? m.skills_reference_visual()
          : m.skills_reference_source()}</InputGroup.Button
      >
    </InputGroup.Addon>
  </InputGroup.Root>
  <p id={`${id}-reference-hint`} class="text-muted-foreground text-xs leading-5">
    {m.skills_reference_hint()}
  </p>
  {#if malformed}<p id={`${id}-reference-error`} class="text-destructive text-sm">
      {m.skills_reference_invalid()}
    </p>{/if}
  <p class="sr-only" role="status">{announcement}</p>
  {#if selection}
    <SkillReferencePicker
      {catalog}
      {selection}
      inline={inlinePicker}
      onClose={closePicker}
      onSelect={(candidate) => {
        const inserted = selection && editor?.replace(selection, candidate.label, candidate.target);
        closePicker();
        if (inserted) announcement = m.skills_reference_inserted();
      }}
      onRemove={() => {
        if (selection) editor?.remove(selection);
        closePicker();
      }}
    />
  {/if}
</div>
