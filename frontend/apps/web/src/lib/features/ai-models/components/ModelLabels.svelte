<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script context="module" lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Label } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  export function getLabels(model: CompletionModel | EmbeddingModel | TranscriptionModel) {
    const labels: {
      label: string | number;
      color: Label.LabelColor;
      tooltip: string;
    }[] = [];

    if ("reasoning" in model && model.reasoning) {
      labels.push({
        tooltip: m.model_tooltip_reasoning(),
        label: m.model_label_reasoning(),
        color: "amethyst"
      });
    }

    if ("vision" in model && model.vision) {
      labels.push({
        tooltip: m.model_tooltip_vision(),
        label: m.model_label_vision(),
        color: "moss"
      });
    }

    if (model.open_source) {
      labels.push({
        tooltip: m.model_tooltip_open_source(),
        label: m.model_label_open_source(),
        color: "green"
      });
    }

    if (model.hosting !== null) {
      labels.push({
        tooltip: m.model_tooltip_hosting(),
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
