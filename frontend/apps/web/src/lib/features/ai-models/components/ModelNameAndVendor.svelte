<script context="module" lang="ts">
  export type OrgInfo = {
    logo: string;
    chartColour: string;
  };

  import openaiLogo from "../assets/logos/openai.jpg";
  import anthropicLogo from "../assets/logos/anthropic.jpg";
  import msLogo from "../assets/logos/ms.jpg";
  import googleLogo from "../assets/logos/google.jpg";
  import mistralLogo from "../assets/logos/mistral.jpg";
  import metaLogo from "../assets/logos/meta.jpg";
  import kblabLogo from "../assets/logos/kblab.jpg";

  export const modelOrgs: Record<string, OrgInfo> = {
    OpenAI: {
      logo: openaiLogo,
      chartColour: "chart-green"
    },
    Anthropic: {
      logo: anthropicLogo,
      chartColour: "chart-moss"
    },
    Microsoft: {
      logo: msLogo,
      chartColour: "chart-red"
    },
    Meta: {
      logo: metaLogo,
      chartColour: "accent-default"
    },
    Google: {
      logo: googleLogo,
      chartColour: "chart-intric"
    },
    Mistral: {
      logo: mistralLogo,
      chartColour: "chart-yellow"
    },
    KBLab: {
      logo: kblabLogo,
      chartColour: "chart-moss"
    },
    Berget: {
      logo: "",
      chartColour: "chart-blue"
    }
  };
</script>

<script lang="ts">
  import { IconCPU } from "@intric/icons/CPU";
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Tooltip } from "@intric/ui";

  export let model:
    | CompletionModel
    | EmbeddingModel
    | TranscriptionModel
    | { org: string; nickname: string; name: string; description: string };
  export let size: "card" | "table" = "table";

  $: logo = model.org && model.org in modelOrgs ? modelOrgs[model.org].logo : null;
</script>

{#if size === "card"}
  <div class="flex items-center justify-start gap-4">
    <div
      class="border-default bg-secondary flex h-12 w-12 items-center justify-center overflow-clip rounded-lg border"
    >
      {#if logo}
        <img src={logo} class="h-full w-full object-cover" alt="{model.org} logo" />
      {:else}
        <IconCPU class="text-muted"></IconCPU>
      {/if}
    </div>
    <h4 class="text-primary text-2xl leading-6 font-extrabold">
      {"nickname" in model ? model.nickname : model.name}
    </h4>
  </div>
{:else}
  <div class="flex items-center justify-start gap-3">
    <div
      class="border-default bg-secondary flex h-7 w-7 items-center justify-center overflow-clip rounded-lg border"
    >
      {#if logo}
        <img src={logo} class="h-full w-full object-cover" alt="{model.org} logo" />
      {:else}
        <IconCPU class="text-muted"></IconCPU>
      {/if}
    </div>
    <Tooltip text={model.description ?? model.name}>
      <h4 class=" text-primary">
        {"nickname" in model ? model.nickname : model.name}
      </h4>
    </Tooltip>
  </div>
{/if}
