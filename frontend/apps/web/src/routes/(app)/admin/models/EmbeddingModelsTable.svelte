<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { EmbeddingModel, ModelProviderPublic } from "@eneo/eneo-js";
  import ProviderGroupedModelTable from "./components/ProviderGroupedModelTable.svelte";

  export let embeddingModels: EmbeddingModel[];
  export let providers: ModelProviderPublic[] = [];
  export let favoriteProviders: string[] = [];
</script>

<ProviderGroupedModelTable
  models={embeddingModels}
  {providers}
  {favoriteProviders}
  modelType="embeddingModel"
/>
