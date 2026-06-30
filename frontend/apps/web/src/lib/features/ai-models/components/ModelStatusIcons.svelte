<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script context="module" lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";

  export type StatusIcon = {
    icon: "deprecated" | "retiring" | "reasoning" | "vision" | "tools";
    tooltip: string;
    color: string;
    ariaLabel: string;
  };

  export function getStatusIcons(
    model: CompletionModel | EmbeddingModel | TranscriptionModel
  ): StatusIcon[] {
    const icons: StatusIcon[] = [];

    if ("deprecation_date" in model && model.deprecation_date) {
      const today = new Date().toISOString().slice(0, 10);
      if (model.deprecation_date <= today) {
        icons.push({
          icon: "deprecated",
          tooltip: m.model_tooltip_deprecated({ date: model.deprecation_date }),
          color: "text-negative-default",
          ariaLabel: m.model_label_deprecated()
        });
      } else {
        icons.push({
          icon: "retiring",
          tooltip: m.model_tooltip_retiring({ date: model.deprecation_date }),
          color: "text-warning-stronger",
          ariaLabel: m.model_label_retiring({ date: model.deprecation_date })
        });
      }
    }

    if ("reasoning" in model && model.reasoning) {
      icons.push({
        icon: "reasoning",
        tooltip: m.model_tooltip_reasoning(),
        color: "text-[oklch(55%_0.15_290)]",
        ariaLabel: m.model_label_reasoning()
      });
    }

    if ("vision" in model && model.vision) {
      icons.push({
        icon: "vision",
        tooltip: m.model_tooltip_vision(),
        color: "text-[oklch(50%_0.12_155)]",
        ariaLabel: m.model_label_vision()
      });
    }

    if ("supports_tool_calling" in model && model.supports_tool_calling) {
      icons.push({
        icon: "tools",
        tooltip: m.model_tooltip_tool_calling(),
        color: "text-[oklch(50%_0.12_250)]",
        ariaLabel: m.model_label_tool_calling()
      });
    }

    return icons;
  }
</script>

<script lang="ts">
  import { Tooltip } from "@eneo/ui";
  import { TriangleAlert, Brain, Eye, Wrench, Clock } from "lucide-svelte";
  import ModelCostBadge from "./ModelCostBadge.svelte";

  export let model: CompletionModel | EmbeddingModel | TranscriptionModel;
  /** Suppress the cost badge — used by surfaces where cost is shown elsewhere. */
  export let showCost: boolean = true;

  $: icons = getStatusIcons(model);

  const iconComponents = {
    deprecated: TriangleAlert,
    retiring: Clock,
    reasoning: Brain,
    vision: Eye,
    tools: Wrench
  };
</script>

<div class="flex items-center gap-2" role="list" aria-label={m.model_capabilities_label()}>
  {#each icons as icon (icon.icon)}
    <Tooltip text={icon.tooltip} asFragment let:trigger>
      {@const tooltipTrigger = trigger[0]}
      <span
        {...tooltipTrigger}
        use:tooltipTrigger.action
        class="{icon.color} cursor-default"
        role="listitem"
        aria-label={icon.ariaLabel}
      >
        <svelte:component this={iconComponents[icon.icon]} size={16} strokeWidth={2} />
      </span>
    </Tooltip>
  {/each}
  {#if showCost}
    <ModelCostBadge {model} dense />
  {/if}
</div>
