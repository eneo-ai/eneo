<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { ImageModel, ModelProviderPublic } from "@eneo/eneo-js";
  import ProviderGroupedModelTable from "./components/ProviderGroupedModelTable.svelte";

  export let imageModels: ImageModel[];
  export let providers: ModelProviderPublic[] = [];
  export let favoriteProviders: string[] = [];
</script>

<ProviderGroupedModelTable
  models={imageModels}
  {providers}
  {favoriteProviders}
  modelType="imageModel"
/>
