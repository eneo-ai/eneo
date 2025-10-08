<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getIntric } from "$lib/core/Intric";
  import SelectSecurityClassification from "$lib/features/security-classifications/components/SelectSecurityClassification.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { IconCheck } from "@intric/icons/check";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IntricError, type Intric, type SecurityClassification } from "@intric/intric-js";
  import { Button, Dialog } from "@intric/ui";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  type Props = { classifications: SecurityClassification[]; onUpdateDone: () => void };

  const { classifications, onUpdateDone }: Props = $props();

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();

  const intric = getIntric();
  const showDryRunDialog = writable(false);

  let classification = $state($currentSpace.security_classification);
  let result = $state<Awaited<
    ReturnType<Intric["securityClassifications"]["impactAnalysis"]>
  > | null>(null);
  let affectedModels = $derived.by(() => {
    if (!result) return [];
    return result.completion_models
      .map(({ nickname }) => {
        return { name: `${nickname} (Completion)` };
      })
      .concat(
        result.embedding_models.map(({ name }) => {
          return { name: `${name} (Embedding)` };
        })
      )
      .concat(
        result.transcription_models.map(({ nickname }) => {
          return { name: `${nickname} (Transcription)` };
        })
      );
  });

  const check = createAsyncState(async () => {
    if (!classification) {
      // If no classification there is no impact
      result = null;
      return;
    }
    result = await intric.securityClassifications.impactAnalysis({
      space: $currentSpace,
      classification
    });
  });

  const update = createAsyncState(async () => {
    try {
      await updateSpace({ security_classification: classification });
      onUpdateDone?.();
      $showDryRunDialog = false;
    } catch (error) {
      alert(error instanceof IntricError ? error.getReadableMessage() : String(error));
    }
  });
</script>

<Settings.Row
  title={m.security_classification()}
  description={m.select_security_classification_for_space()}
>
  {#key $currentSpace.security_classification}
    <SelectSecurityClassification
      value={$currentSpace.security_classification}
      {classifications}
      onSelectedChange={async ({ next }) => {
        classification = next ?? null;
        $showDryRunDialog = true;
        check();
      }}
      dryrun={true}
    ></SelectSecurityClassification>
  {/key}
</Settings.Row>

{#snippet access(title: string, items: { name: string }[] | undefined)}
  {#if items && items.length > 0}
    <div
      class="bg-warning-dimmer border-warning-default text-warning-stronger flex flex-col items-start gap-2 border-l-4 p-2"
    >
      <div>{m.the_following_will_no_longer_be_available({ type: title })}</div>
      <ul class=" list-disc pl-4">
        {#each items as item (item.name)}
          <li>{item.name}</li>
        {/each}
      </ul>
    </div>
  {/if}
{/snippet}

<Dialog.Root openController={showDryRunDialog}>
  <Dialog.Content width="medium">
    <Dialog.Title>{m.change_security_classification()}</Dialog.Title>
    <Dialog.Description
      >{m.you_are_about_to_change_security_classification()}<br />{m.do_you_want_to_proceed()}</Dialog.Description
    >
    <Dialog.Section class="flex flex-col gap-4 p-4">
      <div class="border-default flex flex-col gap-2 border-b">
        <span class="font-bold">{m.selected_classification()}</span>
        <span class="font-mono">{classification?.name ?? m.no_classification()}</span>
      </div>
      <div class="border-default flex flex-col gap-2 border-b">
        <span class="font-bold">{m.affected_resources()}</span>

        {#if check.isLoading}
          <div class="flex gap-2">
            <IconLoadingSpinner class="animate-spin"></IconLoadingSpinner>
            {m.loading_results()}
          </div>
        {:else if affectedModels.length > 0}
          <div class="flex flex-col gap-2">
            {@render access(m.models(), affectedModels)}
            {@render access(m.assistants(), result?.assistants)}
            {@render access(m.group_chats(), result?.group_chats)}
            {@render access(m.apps(), result?.apps)}
            {@render access(m.services(), result?.services)}
          </div>
        {:else}
          <div
            class="bg-positive-dimmer border-positive-default text-positive-stronger flex items-center gap-2 border-l-4 p-2"
          >
            <IconCheck></IconCheck> {m.no_changes_in_functionality()}
          </div>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button onclick={update} variant="primary">{m.confirm()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
