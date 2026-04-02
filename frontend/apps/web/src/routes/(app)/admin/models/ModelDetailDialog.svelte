<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
  import { writable, type Writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import {
    Pencil,
    TriangleAlert,
    Clock,
    ArrowRight,
    ExternalLink
  } from "lucide-svelte";
  import EditModelDialog from "./EditModelDialog.svelte";
  import MigrateModelDialog from "./MigrateModelDialog.svelte";

  export let openController: Writable<boolean>;
  export let model: CompletionModel | EmbeddingModel | TranscriptionModel;
  export let type: "completionModel" | "embeddingModel" | "transcriptionModel";
  export let completionModels: CompletionModel[] = [];

  const showEditDialog = writable(false);
  const showMigrateDialog = writable(false);

  $: isDeprecated =
    "deprecation_date" in model &&
    model.deprecation_date &&
    model.deprecation_date <= new Date().toISOString().slice(0, 10);

  $: isRetiring =
    "deprecation_date" in model &&
    model.deprecation_date &&
    model.deprecation_date > new Date().toISOString().slice(0, 10);

  $: depDate = "deprecation_date" in model ? model.deprecation_date : null;

  function formatTokens(tokens: number | undefined | null): string {
    if (!tokens) return "–";
    if (tokens >= 1_000_000) {
      const val = tokens / 1_000_000;
      return `${val % 1 === 0 ? val.toFixed(0) : val.toFixed(1)}M`;
    }
    if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}K`;
    return tokens.toString();
  }

  const hostingNames: Record<string, string> = {
    usa: "USA", eu: "EU", swe: "Sweden", fra: "France", deu: "Germany",
    gbr: "United Kingdom", chn: "China", can: "Canada", isr: "Israel",
    kor: "South Korea", jpn: "Japan"
  };

</script>

<Dialog.Root {openController}>
  <Dialog.Content width="large">
    <Dialog.Title>
      {model.nickname ?? model.name}
    </Dialog.Title>

    <Dialog.Section>
      <div class="flex flex-col">

        <!-- Deprecation banner -->
        {#if isDeprecated && depDate}
          <div class="flex items-center justify-between gap-6 bg-negative-dimmer/40 px-6 py-4 border-b border-negative-default/20">
            <div class="flex items-center gap-3 text-base text-negative-stronger">
              <TriangleAlert size={20} class="flex-shrink-0" />
              <span>{m.model_tooltip_deprecated({ date: depDate })}</span>
            </div>
            {#if type === "completionModel"}
              <button
                class="flex-shrink-0 inline-flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium text-negative-stronger border border-negative-default/30 hover:bg-negative-dimmer transition-colors"
                on:click={() => { openController.set(false); showMigrateDialog.set(true); }}
              >
                {m.migrate_model_usage()} <ArrowRight size={15} />
              </button>
            {/if}
          </div>
        {:else if isRetiring && depDate}
          <div class="flex items-center gap-3 bg-warning-dimmer/40 px-6 py-4 border-b border-warning-default/20 text-base text-warning-stronger">
            <Clock size={20} class="flex-shrink-0" />
            <span>{m.model_tooltip_retiring({ date: depDate })}</span>
          </div>
        {/if}

        <!-- Properties -->
        <div class="px-6 py-5">
          <table class="w-full">
            <tbody class="text-[15px]">
              <!-- Model identifier -->
              {#if model.nickname && model.name !== model.nickname}
                <tr>
                  <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap w-40">{m.name()}</td>
                  <td class="py-2.5 font-mono text-sm">{model.name}</td>
                </tr>
              {/if}

              <!-- Context window -->
              {#if "max_input_tokens" in model}
                <tr>
                  <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap">Context</td>
                  <td class="py-2.5 font-mono text-sm">{formatTokens(model.max_input_tokens)} in · {formatTokens(model.max_output_tokens)} out</td>
                </tr>
              {/if}

              <!-- Capabilities -->
              {#if "reasoning" in model}
                <tr>
                  <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap">{m.capability_reasoning()}</td>
                  <td class="py-2.5">{#if model.reasoning}<span class="text-positive-default text-lg">✓</span>{:else}<span class="text-muted/30">–</span>{/if}</td>
                </tr>
              {/if}
              {#if "vision" in model}
                <tr>
                  <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap">{m.capability_vision()}</td>
                  <td class="py-2.5">{#if model.vision}<span class="text-positive-default text-lg">✓</span>{:else}<span class="text-muted/30">–</span>{/if}</td>
                </tr>
              {/if}
              {#if "supports_tool_calling" in model}
                <tr>
                  <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap">{m.capability_tools()}</td>
                  <td class="py-2.5">{#if model.supports_tool_calling}<span class="text-positive-default text-lg">✓</span>{:else}<span class="text-muted/30">–</span>{/if}</td>
                </tr>
              {/if}

              <!-- Divider -->
              <tr><td colspan="2" class="py-2"><div class="border-t border-dimmer"></div></td></tr>

              <!-- Hosting -->
              {#if model.hosting}
                <tr>
                  <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap">Hosting</td>
                  <td class="py-2.5">{hostingNames[model.hosting] ?? model.hosting.toUpperCase()}</td>
                </tr>
              {/if}

              <!-- Security -->
              <tr>
                <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap">{m.security()}</td>
                <td class="py-2.5">
                  {#if model.security_classification}
                    {model.security_classification.name}
                  {:else}
                    <span class="text-muted/30">{m.no_classification()}</span>
                  {/if}
                </td>
              </tr>

              <!-- Open source -->
              {#if model.open_source}
                <tr>
                  <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap">{m.model_label_open_source()}</td>
                  <td class="py-2.5"><span class="text-positive-default text-lg">✓</span></td>
                </tr>
              {/if}

              <!-- Divider -->
              {#if model.family || model.org || model.description}
                <tr><td colspan="2" class="py-2"><div class="border-t border-dimmer"></div></td></tr>
              {/if}

              <!-- Metadata -->
              {#if model.family}
                <tr>
                  <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap">Family</td>
                  <td class="py-2.5">{model.family}</td>
                </tr>
              {/if}
              {#if model.org}
                <tr>
                  <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap">Provider</td>
                  <td class="py-2.5">{model.org}</td>
                </tr>
              {/if}
              {#if model.description}
                <tr>
                  <td class="py-2.5 pr-8 text-muted align-top whitespace-nowrap">Description</td>
                  <td class="py-2.5 text-muted">{model.description}</td>
                </tr>
              {/if}
            </tbody>
          </table>

          {#if model.hf_link}
            <a
              href={model.hf_link}
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex items-center gap-1.5 mt-4 text-sm text-accent-default hover:underline"
            >
              HuggingFace <ExternalLink size={13} />
            </a>
          {/if}
        </div>
      </div>
    </Dialog.Section>

    <Dialog.Controls>
      <Button variant="outlined" on:click={() => openController.set(false)}>
        {m.close()}
      </Button>
      <Button
        variant="outlined"
        padding="icon-leading"
        on:click={() => { openController.set(false); showEditDialog.set(true); }}
      >
        <Pencil class="h-4 w-4" />
        {m.model_detail_edit()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<EditModelDialog {model} {type} openController={showEditDialog} />

{#if type === "completionModel"}
  <MigrateModelDialog
    openController={showMigrateDialog}
    sourceModel={model as CompletionModel}
    models={completionModels}
  />
{/if}
