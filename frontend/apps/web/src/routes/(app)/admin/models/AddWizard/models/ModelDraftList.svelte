<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Read-only list of model drafts already queued by the user. Each row exposes
  a "Test" action that calls `validateModel()` against the actual provider,
  and a "Remove" action.
-->

<script lang="ts">
  import { Loader2, CircleCheck, CircleX, Zap, Trash2 } from "lucide-svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getIntric } from "$lib/core/Intric";
  import type { WizardModelDraft } from "../wizardState";
  import type { ModelType } from "./draft";

  let {
    models = $bindable(),
    providerId,
    modelType
  }: {
    models: WizardModelDraft[];
    providerId: string | null;
    modelType: ModelType;
  } = $props();

  const intric = getIntric();

  type ValidationStatus = "idle" | "testing" | "success" | "error";
  type ValidationState = { status: ValidationStatus; message?: string };

  let validationStates = $state<Record<number, ValidationState>>({});

  function statusFor(index: number): ValidationState {
    return validationStates[index] ?? { status: "idle" };
  }

  async function testModel(index: number) {
    if (!providerId) return;
    const model = models[index];
    if (!model) return;

    validationStates = { ...validationStates, [index]: { status: "testing" } };
    try {
      const result = await intric.modelProviders.validateModel(
        { id: providerId },
        { model_name: model.name, model_type: modelType }
      );
      validationStates = {
        ...validationStates,
        [index]: result.success
          ? { status: "success", message: m.model_test_success() }
          : { status: "error", message: result.error || m.model_test_failed() }
      };
    } catch {
      validationStates = {
        ...validationStates,
        [index]: { status: "error", message: m.model_test_connection_error() }
      };
    }
  }

  function removeModel(index: number) {
    models = models.filter((_, i) => i !== index);
    // Re-key validation states so they still line up with the surviving rows.
    const next: Record<number, ValidationState> = {};
    for (const [key, value] of Object.entries(validationStates)) {
      const k = Number(key);
      if (k < index) next[k] = value;
      else if (k > index) next[k - 1] = value;
    }
    validationStates = next;
  }
</script>

{#if models.length > 0}
  <section class="flex flex-col gap-2" aria-label={m.models_to_add_other({ count: models.length })}>
    <h4 class="text-muted-foreground text-sm font-medium">
      {models.length === 1
        ? m.models_to_add_one({ count: models.length })
        : m.models_to_add_other({ count: models.length })}
    </h4>

    <ul class="flex flex-col gap-2">
      {#each models as model, index (model.name + index)}
        {@const vs = statusFor(index)}
        <li
          class="border-border bg-background flex items-center justify-between rounded-lg border p-3"
        >
          <div class="flex min-w-0 flex-1 flex-col">
            <span class="text-foreground font-medium">{model.displayName}</span>
            <span class="text-muted-foreground text-sm">{model.name}</span>
            {#if vs.status === "error" && vs.message}
              <span class="text-destructive mt-1 text-xs">{vs.message}</span>
            {/if}
          </div>

          <div class="ml-2 flex shrink-0 items-center gap-1">
            {#if vs.status === "testing"}
              <Loader2 class="text-muted-foreground size-4 animate-spin" aria-hidden="true" />
            {:else if vs.status === "success"}
              <CircleCheck class="text-positive-default size-4" aria-label={vs.message} />
            {:else if vs.status === "error"}
              <CircleX class="text-destructive size-4" aria-label={vs.message} />
            {/if}

            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onclick={() => testModel(index)}
              disabled={vs.status === "testing" || !providerId}
              title={m.test_model()}
              aria-label={m.test_model()}
            >
              <Zap />
            </Button>

            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              onclick={() => removeModel(index)}
              title={m.remove()}
              aria-label={m.remove()}
              class="text-muted-foreground hover:text-destructive"
            >
              <Trash2 />
            </Button>
          </div>
        </li>
      {/each}
    </ul>
  </section>
{/if}
