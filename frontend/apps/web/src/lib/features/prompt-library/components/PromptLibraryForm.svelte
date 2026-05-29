<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    initial?: { name: string; description: string | null; text: string };
    submitLabel: string;
    onSubmit: (payload: {
      name: string;
      description: string | null;
      text: string;
    }) => Promise<void>;
    onCancel: () => void;
  };

  let { initial, submitLabel, onSubmit, onCancel }: Props = $props();

  function getInitialName() {
    return initial?.name ?? "";
  }

  function getInitialDescription() {
    return initial?.description ?? "";
  }

  function getInitialText() {
    return initial?.text ?? "";
  }

  let name = $state(getInitialName());
  let description = $state(getInitialDescription());
  let text = $state(getInitialText());
  let saving = $state(false);
  let error = $state<string | null>(null);

  const canSubmit = $derived(name.trim().length > 0 && text.trim().length > 0);

  $effect(() => {
    name = getInitialName();
    description = getInitialDescription();
    text = getInitialText();
  });

  async function submit(e: Event) {
    e.preventDefault();
    if (!canSubmit) return;
    saving = true;
    error = null;
    try {
      await onSubmit({
        name: name.trim(),
        description: description.trim() === "" ? null : description.trim(),
        text
      });
    } catch (e) {
      const err = e as { message?: string };
      error = err.message ?? m.governance_prompt_form_save_error();
    } finally {
      saving = false;
    }
  }
</script>

<Card.Root class="mx-auto max-w-3xl">
  <Card.Header>
    <Card.Title>{m.prompt()}</Card.Title>
    <Card.Description>
      {m.governance_prompt_form_desc()}
    </Card.Description>
  </Card.Header>
  <Card.Content>
    <form onsubmit={submit} class="space-y-4">
      <div class="space-y-2">
        <Label for="name">
          {m.name()}
          <span class="text-destructive" aria-hidden="true">*</span>
          <span class="sr-only">{m.field_required()}</span>
        </Label>
        <Input
          id="name"
          bind:value={name}
          required
          maxlength={200}
          placeholder={m.governance_prompt_form_name_placeholder()}
        />
      </div>

      <div class="space-y-2">
        <Label for="description">{m.governance_prompt_form_description_optional()}</Label>
        <Input
          id="description"
          bind:value={description}
          placeholder={m.governance_prompt_form_description_placeholder()}
        />
      </div>

      <div class="space-y-2">
        <Label for="text">
          {m.governance_prompt_form_text_label()}
          <span class="text-destructive" aria-hidden="true">*</span>
          <span class="sr-only">{m.field_required()}</span>
        </Label>
        <Textarea id="text" bind:value={text} rows={12} required />
        <p class="text-muted text-xs">
          {m.governance_prompt_form_characters({ count: text.length })}
        </p>
      </div>

      {#if error}
        <p class="text-destructive text-sm">{error}</p>
      {/if}

      <div class="flex justify-end gap-2 pt-2">
        <Button type="button" variant="outline" onclick={onCancel} disabled={saving}
          >{m.cancel()}</Button
        >
        <Button type="submit" disabled={!canSubmit || saving}>
          {saving ? m.governance_saving() : submitLabel}
        </Button>
      </div>
    </form>
  </Card.Content>
</Card.Root>
