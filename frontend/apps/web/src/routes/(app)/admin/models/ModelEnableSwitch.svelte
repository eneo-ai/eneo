<!-- Copyright (c) 2024 Sundsvalls Kommun -->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Input, Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  type LockableModel = (CompletionModel | EmbeddingModel | TranscriptionModel) & {
    is_locked?: boolean | null | undefined;
    lock_reason?: string | null | undefined;
  };

  export let model: LockableModel;
  export let type: "completionModel" | "embeddingModel" | "transcriptionModel";

  const intric = getIntric();

  // The `intric.models.update` endpoint takes a discriminated union keyed by
  // model type. Branching here lets TypeScript narrow correctly, replacing the
  // old @ts-expect-error hack on a dynamic-key payload.
  async function persistEnabledFlag(next: boolean) {
    const update = { is_org_enabled: next };
    if (type === "completionModel") {
      return intric.models.update({ completionModel: { id: model.id }, update });
    }
    if (type === "embeddingModel") {
      return intric.models.update({ embeddingModel: { id: model.id }, update });
    }
    return intric.models.update({ transcriptionModel: { id: model.id }, update });
  }

  async function toggleEnabled() {
    try {
      const updated = await persistEnabledFlag(!model.is_org_enabled);
      // The narrow API return types differ per branch; we keep the local
      // record in sync without re-narrowing — the table re-fetches anyway.
      model = updated as LockableModel;
      invalidate("admin:models:load");
    } catch (e) {
      toastError(e, m.error_changing_model_status());
    }
  }

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
  <Tooltip text={tooltip}>
    <Input.Switch sideEffect={toggleEnabled} value={model.is_org_enabled} disabled={isDisabled}
    ></Input.Switch>
  </Tooltip>
</div>
