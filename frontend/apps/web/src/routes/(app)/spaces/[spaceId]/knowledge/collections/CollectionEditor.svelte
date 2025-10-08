<script lang="ts">
  import { getIntric } from "$lib/core/Intric";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Dialog, Button, Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  export let mode: "update" | "create" = "create";
  export let collection: { id: string; name: string } | undefined;
  let collectionName = collection?.name ?? "";
  let embeddingModel: { id: string } | undefined = undefined;

  let isProcessing = false;
  async function editCollection() {
    if (!collection) return;
    isProcessing = true;
    try {
      collection = await intric.groups.update({
        group: { id: collection.id },
        update: { name: collectionName }
      });

      refreshCurrentSpace();
      $showDialog = false;
    } catch (error) {
      alert(error);
      console.error(error);
    }
    isProcessing = false;
  }

  async function createCollection() {
    isProcessing = true;
    try {
      await intric.groups.create({
        spaceId: $currentSpace.id,
        name: collectionName,
        embedding_model: embeddingModel
      });

      refreshCurrentSpace();
      collectionName = "";
      $showDialog = false;
    } catch (error) {
      alert(error);
      console.error(error);
    }
    isProcessing = false;
  }

  export let showDialog: Dialog.OpenState | undefined = undefined;
</script>

<Dialog.Root bind:isOpen={showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger asFragment let:trigger>
      <Button variant="primary" is={trigger}>{m.create_collection()}</Button>
    </Dialog.Trigger>
  {/if}

  <Dialog.Content width="medium" form>
    {#if mode === "create"}
      <Dialog.Title>{m.create_new_collection()}</Dialog.Title>
      <Dialog.Description hidden>{m.create_new_collection()}</Dialog.Description>
    {:else}
      <Dialog.Title>{m.edit_collection()}</Dialog.Title>
      <Dialog.Description hidden>{m.edit_collection()}</Dialog.Description>
    {/if}

    <Dialog.Section>
      {#if mode === "create"}
        {#if $currentSpace.embedding_models.length < 1}
          <p
            class="label-warning border-label-default bg-label-dimmer text-label-stronger m-4 rounded-md border px-2 py-1 text-sm"
          >
            <span class="font-bold">{m.warning()}:</span>
            {m.no_embedding_models_warning()}
          </p>
          <div class="border-default border-b"></div>
        {/if}
        <Input.Text
          bind:value={collectionName}
          label={m.name()}
          required
          class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
        ></Input.Text>
        <SelectEmbeddingModel
          hideWhenNoOptions
          bind:value={embeddingModel}
          selectableModels={$currentSpace.embedding_models}
        ></SelectEmbeddingModel>
      {:else}
        <Input.Text
          bind:value={collectionName}
          label={m.name()}
          required
          class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
        ></Input.Text>
      {/if}
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      {#if mode === "create"}
        <Button
          variant="primary"
          on:click={createCollection}
          type="submit"
          disabled={isProcessing || $currentSpace.embedding_models.length === 0}
          >{isProcessing ? m.creating() : m.create_collection()}</Button
        >
      {:else if mode === "update"}
        <Button variant="primary" on:click={editCollection} type="submit"
          >{isProcessing ? m.saving() : m.save_changes()}</Button
        >
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
