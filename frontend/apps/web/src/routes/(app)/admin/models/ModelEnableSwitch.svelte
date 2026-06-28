<!-- Copyright (c) 2024 Sundsvalls Kommun -->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getEneo } from "$lib/core/Eneo";
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@eneo/eneo-js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  type ModelTypeKey = "completionModel" | "embeddingModel" | "transcriptionModel";

  type LockableModel = (CompletionModel | EmbeddingModel | TranscriptionModel) & {
    is_locked?: boolean | null | undefined;
    lock_reason?: string | null | undefined;
  };

  // Rendered via svelte-headless-table's `createRender`, which requires the
  // legacy `export let` API. Keep this file on Svelte 4 component syntax.
  export let model: LockableModel;
  export let type: ModelTypeKey;

  const eneo = getEneo();

  // The `eneo.models.update` endpoint takes a discriminated union keyed by
  // model type. Branching here lets TypeScript narrow correctly.
  async function persistEnabledFlag(next: boolean) {
    const update = { is_org_enabled: next };
    if (type === "completionModel") {
      return eneo.models.update({ completionModel: { id: model.id }, update });
    }
    if (type === "embeddingModel") {
      return eneo.models.update({ embeddingModel: { id: model.id }, update });
    }
    return eneo.models.update({ transcriptionModel: { id: model.id }, update });
  }

  async function handleCheckedChange(next: boolean) {
    try {
      const updated = await persistEnabledFlag(next);
      // Different return types per branch; the table re-fetches anyway.
      model = updated as LockableModel;
      invalidate("admin:models:load");
    } catch (e) {
      toastError(e, m.error_changing_model_status());
    }
  }

  $: modelLabel = "nickname" in model && model.nickname ? model.nickname : model.name;
  $: isMigrated = "migrated_to_model_id" in model && !!model.migrated_to_model_id;
  $: isDisabled = (model.is_locked ?? false) || isMigrated;
  $: tooltip = isMigrated
    ? m.model_tooltip_migrated()
    : model.lock_reason === "credentials"
      ? m.api_credentials_required_for_provider()
      : model.is_org_enabled
        ? m.toggle_to_disable_model()
        : m.toggle_to_enable_model();
</script>

<div class="-ml-3 flex items-center gap-4">
  <Tooltip.Provider delayDuration={150}>
    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <span {...props}>
            <Switch
              checked={model.is_org_enabled}
              onCheckedChange={handleCheckedChange}
              disabled={isDisabled}
              aria-label={`${modelLabel} — ${tooltip}`}
            />
          </span>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content>{tooltip}</Tooltip.Content>
    </Tooltip.Root>
  </Tooltip.Provider>
</div>
