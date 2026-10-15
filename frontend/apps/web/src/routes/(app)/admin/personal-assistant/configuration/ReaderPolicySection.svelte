<!--
    Copyright (c) 2026 Sundsvalls Kommun
    Licensed under the MIT License.
-->
<script lang="ts">
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";
  import BookOpenText from "@lucide/svelte/icons/book-open-text";

  const INHERIT = "inherit";
  const NONE = "none";

  type ReaderOption = { id: string; label: string };
  type Props = {
    readerInherit: boolean;
    readerModelId: string | null;
    /** The models the policy may name: the allowed list when enforced, else all. */
    options: ReaderOption[];
    tenantDefaultLabel: string | null;
    summary: string;
    locked: boolean;
  };
  let {
    readerInherit = $bindable(),
    readerModelId = $bindable(),
    options,
    tenantDefaultLabel,
    summary,
    locked
  }: Props = $props();

  const selected = $derived(readerInherit ? INHERIT : (readerModelId ?? NONE));
  const inheritLabel = $derived(
    tenantDefaultLabel
      ? m.reader_option_inherit({ model: tenantDefaultLabel })
      : m.reader_option_inherit_none()
  );
  const selectedLabel = $derived(
    selected === INHERIT
      ? inheritLabel
      : selected === NONE
        ? m.reader_option_none()
        : (options.find((option) => option.id === selected)?.label ?? m.reader_option_none())
  );
</script>

<PolicySection
  id="reader"
  title={m.governance_reader_heading()}
  description={m.governance_reader_section_desc()}
  {summary}
  summaryVariant="outline"
>
  {#snippet icon()}
    <BookOpenText class="h-5 w-5" />
  {/snippet}
  <div class="grid gap-2 sm:grid-cols-[minmax(0,1fr)_16rem] sm:items-center">
    <div>
      <Label for="reader-policy-model">{m.reader_model_label()}</Label>
      <p class="text-secondary mt-1 text-sm">{m.reader_never()} {m.governance_reader_note()}</p>
    </div>
    <Select.Root
      type="single"
      value={selected}
      onValueChange={(value) => {
        readerInherit = value === INHERIT;
        readerModelId = value === INHERIT || value === NONE ? null : value;
      }}
    >
      <Select.Trigger id="reader-policy-model" class="w-full">{selectedLabel}</Select.Trigger>
      <Select.Content>
        <Select.Item value={INHERIT} label={inheritLabel}>{inheritLabel}</Select.Item>
        <Select.Item value={NONE} label={m.reader_option_none()}
          >{m.reader_option_none()}</Select.Item
        >
        {#each options as option (option.id)}
          <Select.Item value={option.id} label={option.label}>{option.label}</Select.Item>
        {/each}
      </Select.Content>
    </Select.Root>
  </div>
  {#if locked}
    <p class="text-secondary mt-3 text-sm">{m.governance_reader_locked_note()}</p>
  {/if}
</PolicySection>
