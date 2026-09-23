<script lang="ts">
  import { goto } from "$app/navigation";
  import { getEneo } from "$lib/core/Eneo";
  import SelectEmbeddingModel from "$lib/features/ai-models/components/SelectEmbeddingModel.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";
  import { writable, type Writable } from "svelte/store";

  const eneo = getEneo();
  const {
    refreshCurrentSpace,
    state: { currentSpace }
  } = getSpacesManager();

  export let mode: "update" | "create" = "create";
  export let collection: { id: string; name: string } | undefined;
  let collectionName = collection?.name ?? "";
  let embeddingModel: { id: string } | undefined = undefined;
  const nameId = useId();

  let isProcessing = false;
  async function editCollection() {
    if (!collection) return;
    isProcessing = true;
    try {
      collection = await eneo.groups.update({
        group: { id: collection.id },
        update: { name: collectionName }
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
        embedding_model: embeddingModel
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

  export let showDialog: Writable<boolean> = writable(false);
</script>

<Dialog.Root bind:open={$showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props}>{m.create_collection()}</Button>
      {/snippet}
    </Dialog.Trigger>
  {/if}

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form
      class="contents"
      onsubmit={(event) => {
        event.preventDefault();
        if (mode === "create") createCollection();
        else editCollection();
      }}
    >
      <Dialog.Header class={dialogLayout.header}>
        {#if mode === "create"}
          <Dialog.Title>{m.create_new_collection()}</Dialog.Title>
          <Dialog.Description class="sr-only">{m.create_new_collection()}</Dialog.Description>
        {:else}
          <Dialog.Title>{m.edit_collection()}</Dialog.Title>
          <Dialog.Description class="sr-only">{m.edit_collection()}</Dialog.Description>
        {/if}
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
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
            <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
              <Field.Label for={nameId}>
                {m.name()}
                <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
              </Field.Label>
              <Input id={nameId} bind:value={collectionName} required />
            </Field.Field>
            <SelectEmbeddingModel
              hideWhenNoOptions
              bind:value={embeddingModel}
              selectableModels={$currentSpace.embedding_models}
            ></SelectEmbeddingModel>
          {:else}
            <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
              <Field.Label for={nameId}>
                {m.name()}
                <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
              </Field.Label>
              <Input id={nameId} bind:value={collectionName} required />
            </Field.Field>
          {/if}
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        {#if mode === "create"}
          <Button
            type="submit"
            disabled={isProcessing || $currentSpace.embedding_models.length === 0}
            >{isProcessing ? m.creating() : m.create_collection()}</Button
          >
        {:else if mode === "update"}
          <Button type="submit">{isProcessing ? m.saving() : m.save_changes()}</Button>
        {/if}
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
