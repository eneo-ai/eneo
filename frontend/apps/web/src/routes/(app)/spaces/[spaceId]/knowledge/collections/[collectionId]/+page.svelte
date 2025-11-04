<script lang="ts">
  import { Page } from "$lib/components/layout";
  import BlobUpload from "./BlobUpload.svelte";
  import BlobCreate from "./BlobCreate.svelte";
  import BlobTable from "./BlobTable.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived } from "svelte/store";
  import { Tooltip } from "@intric/ui";

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
    >Eneo.ai – {data.currentSpace.personal ? "Personal" : data.currentSpace.name} – Knowledge</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: "Knowledge",
        href: `/spaces/${$currentSpace.routeId}/knowledge?tab=collections`
      }}
      title={data.collection.name}
    ></Page.Title>
    <Tooltip
      text={$disabledModelInUse ? "Enable model in settings to add text" : undefined}
      placement="left"
    >
      <Page.Flex>
        <BlobCreate disabled={$disabledModelInUse || data.readonly} collection={data.collection}></BlobCreate>
        <BlobUpload
          disabled={$disabledModelInUse || data.readonly}
          collection={data.collection}
          currentBlobs={data.blobs}
        ></BlobUpload>
      </Page.Flex>
    </Tooltip>
  </Page.Header>
  <Page.Main>
    <BlobTable blobs={data.blobs} canEdit={!data.readonly}></BlobTable>
  </Page.Main>
</Page.Root>
