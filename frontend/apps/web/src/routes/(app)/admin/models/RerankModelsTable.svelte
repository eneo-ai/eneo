<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { ModelProviderPublic, RerankModel } from "@eneo/eneo-js";
  import ProviderGroupedModelTable from "./components/ProviderGroupedModelTable.svelte";

  export let rerankModels: RerankModel[];
  export let providers: ModelProviderPublic[] = [];
  export let favoriteProviders: string[] = [];
</script>

<ProviderGroupedModelTable
  models={rerankModels}
  {providers}
  {favoriteProviders}
  modelType="rerankModel"
/>
