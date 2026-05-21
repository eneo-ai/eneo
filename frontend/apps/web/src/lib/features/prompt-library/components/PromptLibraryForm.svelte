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
      error = err.message ?? "Kunde inte spara prompten.";
    } finally {
      saving = false;
    }
  }
</script>

<Card.Root class="mx-auto max-w-3xl">
  <Card.Header>
    <Card.Title>Prompt</Card.Title>
    <Card.Description>
      Promptbiblioteket gör det möjligt att dela samma system-prompt till alla användares personliga
      chatt.
    </Card.Description>
  </Card.Header>
  <Card.Content>
    <form onsubmit={submit} class="space-y-4">
      <div class="space-y-2">
        <Label for="name">Namn</Label>
        <Input
          id="name"
          bind:value={name}
          required
          maxlength={200}
          placeholder="t.ex. Standard personlig chatt"
        />
      </div>

      <div class="space-y-2">
        <Label for="description">Beskrivning (valfritt)</Label>
        <Input
          id="description"
          bind:value={description}
          placeholder="En kort beskrivning som hjälper admin att känna igen prompten"
        />
      </div>

      <div class="space-y-2">
        <Label for="text">Prompt-text</Label>
        <Textarea id="text" bind:value={text} rows={12} required />
        <p class="text-muted text-xs">{text.length} tecken</p>
      </div>

      {#if error}
        <p class="text-destructive text-sm">{error}</p>
      {/if}

      <div class="flex justify-end gap-2 pt-2">
        <Button type="button" variant="outline" onclick={onCancel} disabled={saving}>Avbryt</Button>
        <Button type="submit" disabled={!canSubmit || saving}>
          {saving ? "Sparar..." : submitLabel}
        </Button>
      </div>
    </form>
  </Card.Content>
</Card.Root>
