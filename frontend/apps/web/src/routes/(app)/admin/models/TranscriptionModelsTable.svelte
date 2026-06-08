<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { TranscriptionModel, ModelProviderPublic } from "@intric/intric-js";
  import ProviderGroupedModelTable from "./components/ProviderGroupedModelTable.svelte";

  export let transcriptionModels: TranscriptionModel[];
  export let providers: ModelProviderPublic[] = [];
  export let favoriteProviders: string[] = [];
</script>

<ProviderGroupedModelTable
  models={transcriptionModels}
  {providers}
  {favoriteProviders}
  modelType="transcriptionModel"
/>
