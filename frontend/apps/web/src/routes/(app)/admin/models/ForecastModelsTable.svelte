<!--
  Forecast models come with the installation, under Eneo's tool service: no
  provider or model to add here, so the table gets no add-model wizard.
-->

<script lang="ts">
  import type { ForecastModel, ModelProviderPublic } from "@eneo/eneo-js";
  import ProviderGroupedModelTable from "./components/ProviderGroupedModelTable.svelte";

  let {
    forecastModels,
    providers = []
  }: { forecastModels: ForecastModel[]; providers?: ModelProviderPublic[] } = $props();
</script>

<ProviderGroupedModelTable models={forecastModels} {providers} modelType="forecastModel" />
