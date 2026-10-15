<!--
  Copyright (c) 2026 Sundsvalls Kommun

  The organisation's default reader model: the model that reads long sources
  and attached files part by part when an assistant digests them. It sits
  above the completion models list rather than in a per-model dialog, because
  the choice is a tenant-wide one with a security-classification consequence
  spaces need to see.
-->
<script lang="ts">
  import type { CompletionModel } from "@eneo/eneo-js";
  import { invalidate } from "$app/navigation";
  import * as Card from "$lib/components/ui/card/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { toastError } from "$lib/core/errors";
  import { getEneo } from "$lib/core/Eneo.js";
  import { m } from "$lib/paraglide/messages";
  import BookOpenText from "@lucide/svelte/icons/book-open-text";

  const NONE = "none";

  type Props = { completionModels: CompletionModel[] };
  let { completionModels }: Props = $props();

  const eneo = getEneo();
  const uid = $props.id();

  // Only the tenant's own, enabled models can take the role; a deprecated or
  // migrated model is kept visible while it still holds it, so it can be moved.
  const current = $derived(completionModels.find((model) => model.is_org_reader) ?? null);
  const options = $derived(
    completionModels.filter(
      (model) =>
        model.provider_id != null &&
        model.is_org_enabled &&
        (model.id === current?.id || (!model.is_deprecated && !model.migrated_to_model_id))
    )
  );
  const selected = $derived(current?.id ?? NONE);
  let saving = $state(false);

  function classificationName(model: CompletionModel): string {
    return model.security_classification?.name ?? m.reader_unclassified();
  }

  function label(model: CompletionModel): string {
    return `${model.nickname ?? model.name} · ${classificationName(model)}`;
  }

  async function choose(value: string) {
    if (saving || value === selected) return;
    saving = true;
    try {
      if (value === NONE) {
        if (current)
          await eneo.tenantModels.updateCompletion({ id: current.id }, { is_reader: false });
      } else {
        await eneo.tenantModels.updateCompletion({ id: value }, { is_reader: true });
      }
      await invalidate("admin:model-providers:load");
    } catch (e) {
      toastError(e);
    }
    saving = false;
  }
</script>

<Card.Root class="mt-4 mr-3 mb-6 gap-0 py-0" role="group" aria-labelledby={`${uid}-heading`}>
  <Card.Header class="border-dimmer border-b p-5 [.border-b]:pb-5">
    <div class="flex items-start gap-3">
      <BookOpenText class="text-accent-default mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
      <div class="flex flex-col gap-1">
        <Card.Title id={`${uid}-heading`} class="text-default font-semibold">
          {m.reader_default_heading()}
        </Card.Title>
        <Card.Description class="text-secondary max-w-[72ch] leading-relaxed">
          {m.reader_one_mode()}
        </Card.Description>
      </div>
    </div>
  </Card.Header>
  <Card.Content class="grid gap-6 p-5 md:grid-cols-[minmax(0,1fr)_minmax(16rem,20rem)]">
    <p class="text-secondary max-w-[72ch] text-sm leading-relaxed">
      {m.reader_never()}
      {m.reader_default_inherit_note()}
    </p>
    <div class="flex flex-col gap-2">
      <Label for={`${uid}-select`}>{m.reader_model_label()}</Label>
      <Select.Root type="single" value={selected} onValueChange={choose} disabled={saving}>
        <Select.Trigger id={`${uid}-select`} class="w-full">
          {current ? label(current) : m.reader_none()}
        </Select.Trigger>
        <Select.Content>
          <Select.Item value={NONE} label={m.reader_none()}>{m.reader_none()}</Select.Item>
          {#each options as model (model.id)}
            <Select.Item value={model.id} label={label(model)}>{label(model)}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
      {#if current}
        <p class="text-secondary text-sm">
          {m.security_classification()}:
          <span class="text-default font-medium">{classificationName(current)}</span>
        </p>
      {/if}
    </div>
  </Card.Content>
</Card.Root>
