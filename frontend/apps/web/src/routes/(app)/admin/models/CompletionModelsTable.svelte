<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Thin wrapper around the generic ProviderGroupedModelTable. Kept as a
  named entry point so the route's +page.svelte can stay declarative and
  so the wrapper has a place to grow type-specific pre-processing if it
  ever needs to.
-->

<script lang="ts">
  import type { CompletionModel, ModelProviderPublic } from "@intric/intric-js";
  import ProviderGroupedModelTable from "./components/ProviderGroupedModelTable.svelte";

  export let completionModels: CompletionModel[];
  export let providers: ModelProviderPublic[] = [];
  export let favoriteProviders: string[] = [];
</script>

<ProviderGroupedModelTable
  models={completionModels}
  {providers}
  {favoriteProviders}
  modelType="completionModel"
/>
