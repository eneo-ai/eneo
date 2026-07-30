<script lang="ts">
  import { goto } from "$app/navigation";
  import { getEneo } from "$lib/core/Eneo";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import ChunkSettings from "$lib/features/knowledge/components/ChunkSettings.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Dialog, Button, Input } from "@eneo/ui";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  export let mode: "update" | "create" = "create";
  export let collection:
    | { id: string; name: string; chunk_size?: number | null; chunk_overlap?: number | null }
    | undefined;
  let collectionName = collection?.name ?? "";
  let embeddingModel: { id: string } | undefined = undefined;
  let chunkSize: number | null = collection?.chunk_size ?? null;
  let chunkOverlap: number | null = collection?.chunk_overlap ?? null;

  let isProcessing = false;
  async function editCollection() {
    if (!collection) return;
    isProcessing = true;
    try {
      collection = await eneo.groups.update({
        group: { id: collection.id },
        update: { name: collectionName, chunk_size: chunkSize, chunk_overlap: chunkOverlap }
      });

      refreshCurrentSpace();
      $showDialog = false;
    } catch (error) {
      toastError(error);
      console.error(error);
    }
    isProcessing = false;
  }

  async function createCollection() {
    isProcessing = true;
    try {
      const { id: spaceId, routeId } = $currentSpace;
      const newCollection = await eneo.groups.create({
        spaceId,
        name: collectionName,
        embedding_model: embeddingModel,
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap
      });

      await refreshCurrentSpace("knowledge");
      collectionName = "";
      embeddingModel = undefined;
      $showDialog = false;
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic path with routeId and collection id
      await goto(`/spaces/${routeId}/knowledge/collections/${newCollection.id}`);
    } catch (error) {
      toastError(error);
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
        <ChunkSettings bind:chunkSize bind:chunkOverlap />
      {:else}
        <Input.Text
          bind:value={collectionName}
          label={m.name()}
          required
          class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
        ></Input.Text>
        <ChunkSettings bind:chunkSize bind:chunkOverlap />
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
