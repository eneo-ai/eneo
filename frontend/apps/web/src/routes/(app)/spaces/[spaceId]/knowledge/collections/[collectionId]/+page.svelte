<script lang="ts">
  import { Page } from "$lib/components/layout";
  import BlobUpload from "./BlobUpload.svelte";
  import BlobCreate from "./BlobCreate.svelte";
  import BlobTable from "./BlobTable.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived } from "svelte/store";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";

  export let data;

  const {
    state: { currentSpace }
  } = getSpacesManager();

  // Derived store to check for disabled models in use
  const disabledModelInUse = derived(currentSpace, ($currentSpace) => {
    const modelsInSpace = $currentSpace.embedding_models.map((model) => model.id);
    return !modelsInSpace.includes(data.collection.embedding_model?.id ?? "no_model");
  });
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {m.knowledge()}</title
  >
</svelte:head>

{#snippet blobActions()}
  <Page.Flex>
    <BlobCreate disabled={$disabledModelInUse || data.readonly} collection={data.collection}
    ></BlobCreate>
    <BlobUpload
      disabled={$disabledModelInUse || data.readonly}
      collection={data.collection}
      currentBlobs={data.blobs}
    ></BlobUpload>
  </Page.Flex>
{/snippet}

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: "Knowledge",
        href: `/spaces/${$currentSpace.routeId}/knowledge?tab=collections`
      }}
      title={data.collection.name}
    ></Page.Title>
    {#if $disabledModelInUse}
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <div {...props}>{@render blobActions()}</div>
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content side="left">{m.collection_enable_model_to_add_text()}</Tooltip.Content>
      </Tooltip.Root>
    {:else}
      {@render blobActions()}
    {/if}
  </Page.Header>
  <Page.Main>
    <BlobTable blobs={data.blobs} canEdit={!data.readonly}></BlobTable>
  </Page.Main>
</Page.Root>
