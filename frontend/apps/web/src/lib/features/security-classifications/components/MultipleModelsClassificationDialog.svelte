<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import {
    IntricError,
    type CompletionModel,
    type EmbeddingModel,
    type SecurityClassification,
    type TranscriptionModel
  } from "@intric/intric-js";
  import { getSecurityClassificationService } from "../SecurityClassificationsService.svelte";
  import ModelNameAndVendor from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import SelectSecurityClassification from "./SelectSecurityClassification.svelte";
  import { getIntric } from "$lib/core/Intric";
  import { Button } from "@intric/ui";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { m } from "$lib/paraglide/messages";

  type Props =
    | {
        models: CompletionModel[];
        type: "completionModel";
      }
    | {
        models: EmbeddingModel[];
        type: "embeddingModel";
      }
    | {
        models: TranscriptionModel[];
        type: "transcriptionModel";
      };

  const { models, type }: Props = $props();
  const security = getSecurityClassificationService();
  const intric = getIntric();

  function createOrgFilter(org: string | null | undefined) {
    return function (model: { org?: string | null | undefined }) {
      return model.org === org;
    };
  }

  function listOrgs(models: { org?: string | null | undefined }[]) {
    const uniqueOrgs = new Set<string>();

    for (const model of models) {
      if (model.org) uniqueOrgs.add(model.org);
    }

    return uniqueOrgs;
  }

  const uniqueOrgs = $derived(listOrgs(models));

  async function update(
    model: { id: string },
    security_classification?: SecurityClassification | null
  ) {
    if (security_classification === undefined) return;
    try {
      // @ts-expect-error doesnt understand [type]
      await intric.models.update({ [type]: model, update: { security_classification } });
    } catch (error) {
      alert(error instanceof IntricError ? error.getReadableMessage() : String(error));
    }
  }

  const label: Record<typeof type, string> = {
    completionModel: m.configure_completion_models(),
    embeddingModel: m.configure_embedding_models(),
    transcriptionModel: m.configure_transcription_models()
  };

  const countClassifiedModels = () => {
    const total = models.length;
    const classified = models.filter(
      ({ security_classification }) => security_classification !== null
    ).length;
    return m.classified_of_total({ classified, total });
  };

  let classifiedCount = $state(countClassifiedModels());
  let isOpen = $state(false);
</script>

<div class="flex flex-col gap-2">
  <div class="border-default flex h-14 items-center border-b">
    <Button onclick={() => (isOpen = !isOpen)} class=" font-mono">
      <IconChevronRight class={[isOpen && "rotate-90"]}></IconChevronRight>
      {label[type]}</Button
    >
    <div class="flex-grow"></div>
    <div
      class="text-accent-stronger bg-accent-dimmer border-accent-default rounded-full border px-3 py-0.5"
    >
      {classifiedCount}
    </div>
  </div>

  {#if isOpen}
    <div
      class="border-stronger bg-primary relative z-10 row-span-1 flex flex-col gap-4 rounded-md border shadow-md"
    >
      {#each uniqueOrgs as org (org)}
        {@const filteredModels = models.filter(createOrgFilter(org))}
        <div class="flex flex-col">
          <span class="border-default border-b p-4 font-mono">{org}</span>
          <div class="flex min-h-12 flex-col">
            {#each filteredModels as model (model.id)}
              <div class="hover:bg-hover-dimmer border-dimmer flex justify-between border-b pl-4">
                <ModelNameAndVendor {model}></ModelNameAndVendor>
                <div class="-mb-[1px] flex w-2/3 flex-col">
                  <SelectSecurityClassification
                    value={model.security_classification ?? null}
                    classifications={security.classifications}
                    onSelectedChange={async ({ next }) => {
                      try {
                        await update(model, next);
                        model.security_classification = next;
                        classifiedCount = countClassifiedModels();
                      } catch (error) {
                        alert(error);
                      }
                    }}
                  ></SelectSecurityClassification>
                </div>
              </div>
            {/each}
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
