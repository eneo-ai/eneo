<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog } from "@intric/ui";
  import { type Writable } from "svelte/store";
  import {
    IntricError,
    type CompletionModel,
    type EmbeddingModel,
    type TranscriptionModel
  } from "@intric/intric-js";
  import SelectSecurityClassification from "./SelectSecurityClassification.svelte";
  import { getSecurityContext } from "../SecurityContext";
  import { getIntric } from "$lib/core/Intric";
  import { invalidate } from "$app/navigation";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    model: CompletionModel | EmbeddingModel | TranscriptionModel;
    type: "completionModel" | "embeddingModel" | "transcriptionModel";
    openController: Writable<boolean>;
  };

  const { model, type, openController }: Props = $props();

  const classifications = getSecurityContext().security_classifications;
  const intric = getIntric();

  let value = $derived(model.security_classification ?? null);

  const update = createAsyncState(async () => {
    try {
      await intric.models.update(
        //@ts-expect-error ts doesn't understand this
        {
          [type]: model,
          update: { security_classification: value }
        }
      );
      invalidate("admin:models:load");
      $openController = false;
    } catch (error) {
      alert(error instanceof IntricError ? error.getReadableMessage() : String(error));
    }
  });
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.select_security_classification()}</Dialog.Title>

    <Dialog.Section class="p-4" scrollable={false}>
      <SelectSecurityClassification {classifications} bind:value></SelectSecurityClassification>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button
        variant="primary"
        onclick={update}
        type="submit"
        disabled={value?.id === model.security_classification?.id || update.isLoading}
        >{update.isLoading ? m.saving() : m.save_changes()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
