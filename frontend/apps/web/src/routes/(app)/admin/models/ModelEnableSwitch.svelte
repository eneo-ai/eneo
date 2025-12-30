<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getAppContext } from "$lib/core/AppContext";
  import { getIntric } from "$lib/core/Intric";
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Input, Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  interface ImageModel {
    id: string;
    name: string;
    is_org_enabled: boolean;
    is_locked?: boolean | null;
    lock_reason?: string | null;
  }

  export let model: (CompletionModel | EmbeddingModel | TranscriptionModel | ImageModel) & {
    is_locked?: boolean | null | undefined;
    lock_reason?: string | null | undefined;
  };
  export let type: "completionModel" | "embeddingModel" | "transcriptionModel" | "imageModel";

  const intric = getIntric();
  const { environment } = getAppContext();

  async function toggleEnabled() {
    try {
      if (type === "imageModel") {
        model = await intric.imageModels.update({
          imageModel: { id: model.id },
          update: {
            is_org_enabled: !model.is_org_enabled
          }
        });
      } else {
        model = await intric.models.update(
          //@ts-expect-error ts doesn't understand this
          {
            [type]: model,
            update: {
              is_org_enabled: !model.is_org_enabled
            }
          }
        );
      }
      invalidate("admin:models:load");
    } catch (e) {
      alert(`Error changing status of ${model.name}`);
    }
  }

  $: tooltip = model.lock_reason === "credentials"
    ? m.api_credentials_required_for_provider()
    : model.is_org_enabled
      ? m.toggle_to_disable_model()
      : m.toggle_to_enable_model();
</script>

<div class="-ml-3 flex items-center gap-4">
  <Tooltip text={tooltip}>
    <Input.Switch
      sideEffect={toggleEnabled}
      value={model.is_org_enabled}
      disabled={model.is_locked ?? false}
    ></Input.Switch>
  </Tooltip>
</div>
