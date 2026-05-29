<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Read-only cell that surfaces a model's security classification next to the
  other configurable fields in the table. Editing happens in the "Edit model"
  dialog — keeping it there mirrors how the other fields work and avoids two
  places to change the same value.
-->

<script lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";

  type AnyModel = CompletionModel | EmbeddingModel | TranscriptionModel;

  // Rendered via svelte-headless-table's `createRender`, which requires the
  // legacy `export let` API. Keep this file on Svelte 4 component syntax.
  export let model: AnyModel;

  $: classification = model.security_classification ?? null;
</script>

{#if classification}
  <span class="text-primary truncate px-2 text-sm capitalize">{classification.name}</span>
{:else}
  <span class="text-muted-foreground/70 px-2 text-sm">{m.no_classification()}</span>
{/if}
