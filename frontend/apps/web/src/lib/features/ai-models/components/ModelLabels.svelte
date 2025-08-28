<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script context="module" lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  export function getLabels(model: CompletionModel | EmbeddingModel | TranscriptionModel) {
    const labels: {
      label: string | number;
      color: Label.LabelColor;
      tooltip: string;
    }[] = [];

    if ("reasoning" in model && model.reasoning) {
      labels.push({
        tooltip: "This model can use reasoning to refine its answers",
        label: "Reasoning",
        color: "amethyst"
      });
    }

    if ("vision" in model && model.vision) {
      labels.push({
        tooltip: "This model can process image files",
        label: "Vision",
        color: "moss"
      });
    }

    if (model.open_source) {
      labels.push({
        tooltip: "This model is open source",
        label: "Open Source",
        color: "green"
      });
    }

    if ("litellm_model_name" in model && model.litellm_model_name) {
      labels.push({
        tooltip: "This model uses LiteLLM proxy",
        label: "LiteLLM",
        color: "blue"
      });
    }

    if (model.hosting !== null) {
      labels.push({
        tooltip: "Region this model is hosted in",
        label: model.hosting.toUpperCase(),
        color: model.hosting === "usa" ? "orange" : "green"
      });
    }

    // if (model.stability === "experimental") {
    //   labels.push({
    //     tooltip: "Stability",
    //     label: "Experimental",
    //     color: "yellow"
    //   });
    // }

    return labels;
  }
</script>

<script lang="ts">
  export let model: CompletionModel | EmbeddingModel | TranscriptionModel;
  $: labels = getLabels(model);
</script>

<Label.List content={labels} />
