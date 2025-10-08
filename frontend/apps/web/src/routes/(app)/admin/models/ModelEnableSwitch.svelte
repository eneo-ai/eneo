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

  export let model: (CompletionModel | EmbeddingModel | TranscriptionModel) & {
    is_locked?: boolean | null | undefined;
  };
  export let type: "completionModel" | "embeddingModel" | "transcriptionModel";

  const intric = getIntric();
  const { environment } = getAppContext();

  async function toggleEnabled() {
    try {
      model = await intric.models.update(
        //@ts-expect-error ts doesn't understand this
        {
          [type]: model,
          update: {
            is_org_enabled: !model.is_org_enabled
          }
        }
      );
      invalidate("admin:models:load");
    } catch (e) {
      alert(`Error changing status of ${model.name}`);
    }
  }

  $: tooltip = model.is_locked
    ? m.model_available_on_request({ email: environment.salesEmail })
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
