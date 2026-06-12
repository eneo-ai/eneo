<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { resolve } from "$app/paths";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import { AlertCircle, Info, Sparkles } from "lucide-svelte";
  import PolicySection from "./PolicySection.svelte";

  type PromptOption = {
    id: string;
    name: string;
    description?: string | null;
  };

  type Props = {
    promptEnabled: boolean;
    selectedPromptId: string | null;
    promptOptions: PromptOption[];
    promptSummary: string;
    badgeVariant: (enabled: boolean, valid: boolean) => "default" | "outline" | "destructive";
  };

  let {
    promptEnabled = $bindable(),
    selectedPromptId = $bindable(),
    promptOptions,
    promptSummary,
    badgeVariant
  }: Props = $props();
</script>

<PolicySection
  id="prompt"
  title={m.governance_prompt_heading()}
  description={m.governance_prompt_section_desc()}
  summary={promptSummary}
  summaryVariant={badgeVariant(promptEnabled, selectedPromptId !== null)}
>
  {#snippet icon()}
    <Sparkles class="h-5 w-5" />
  {/snippet}

  <div class="flex items-center justify-between gap-3">
    <Label for="prompt-enabled" class="text-sm font-medium">
      {m.governance_prompt_toggle_label()}
    </Label>
    <Switch id="prompt-enabled" bind:checked={promptEnabled} aria-describedby="prompt-help" />
  </div>

  {#if promptEnabled}
    {#if promptOptions.length === 0}
      <Alert.Root class="border-caution/35 bg-caution/8">
        <Info class="text-caution" />
        <Alert.Description class="text-secondary">
          {m.governance_prompt_library_empty()}
          <a
            class="text-accent-default mt-1 inline-block underline"
            href={resolve("/admin/prompt-library")}
          >
            {m.governance_prompt_create_in_library()}
          </a>
        </Alert.Description>
      </Alert.Root>
    {:else}
      <p id="prompt-help" class="text-secondary text-sm">
        {m.governance_prompt_help_enabled()}
      </p>
      <RadioGroup.Root bind:value={() => selectedPromptId ?? "", (v) => (selectedPromptId = v)}>
        <div class="space-y-2">
          {#each promptOptions as p (p.id)}
            <Label
              for={`p-${p.id}`}
              class="border-default hover:border-stronger aria-checked:border-accent-default flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors"
            >
              <RadioGroup.Item value={p.id} id={`p-${p.id}`} class="mt-0.5" />
              <div class="flex-1">
                <div class="text-sm font-medium">{p.name}</div>
                {#if p.description}
                  <div class="text-secondary mt-0.5 text-xs">{p.description}</div>
                {/if}
              </div>
            </Label>
          {/each}
        </div>
      </RadioGroup.Root>
      {#if !selectedPromptId}
        <p class="text-destructive flex items-center gap-2 text-sm" role="alert">
          <AlertCircle class="h-4 w-4 shrink-0" aria-hidden="true" />
          {m.governance_prompt_error_required()}
        </p>
      {/if}
    {/if}
  {:else}
    <p id="prompt-help" class="text-secondary text-sm">
      {m.governance_prompt_help_disabled()}
    </p>
  {/if}
</PolicySection>
