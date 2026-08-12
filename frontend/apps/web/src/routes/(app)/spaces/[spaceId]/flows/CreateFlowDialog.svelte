<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { getAppContext } from "$lib/core/AppContext";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getFlowsManager } from "$lib/features/flows/FlowsManager";
  import { writeAIBuilderSeed } from "$lib/features/flows/ai-builder/flowAIBuilderSeed";
  import { IconWorkflow } from "@eneo/icons/workflow";
  import { EneoError } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace }
  } = getSpacesManager();
  const { user } = getAppContext();

  const flowsManager = getFlowsManager();
  let showDialog = $state(false);
  const canCreateFlowManually = user.hasPermission("flows_manage");
  const canUseAIBuilder = user.hasPermission({
    allOf: ["flows_manage", "flows_ai_builder"]
  });

  let mode = $state<"prompt" | "manual">("prompt");
  let taskDescription = $state("");
  let newFlowName = $state("");
  let openAfterCreation = $state(true);
  let createError = $state<string | null>(null);

  const taskExamples = [
    m.flow_create_example_summarize,
    m.flow_create_example_review,
    m.flow_create_example_translate,
    m.flow_create_example_decision
  ];

  function reset() {
    mode = canUseAIBuilder ? "prompt" : "manual";
    taskDescription = "";
    newFlowName = "";
    createError = null;
  }

  function openCreateDialog() {
    reset();
    showDialog = true;
  }

  function continueToAIBuilder() {
    writeAIBuilderSeed($currentSpace.id, taskDescription);
    showDialog = false;
    reset();
    goto(resolve(`/spaces/${$currentSpace.routeId}/flows/ai-builder`));
  }

  async function createFlow() {
    try {
      const created = await flowsManager.createFlow(newFlowName);
      if (openAfterCreation && created.id) {
        goto(resolve(`/spaces/${$currentSpace.routeId}/flows/${created.id}`));
      }
      newFlowName = "";
      showDialog = false;
      reset();
    } catch (error) {
      createError = error instanceof EneoError ? error.getReadableMessage() : String(error);
    }
  }
</script>

<Button variant="default" onclick={openCreateDialog}>
  <IconWorkflow class="size-4" />
  {m.flow_create()}
</Button>

<Dialog.Root bind:open={showDialog}>
  <Dialog.Content
    class="flex max-h-[calc(100dvh-1.5rem)] w-[calc(100%-1.5rem)] !max-w-2xl flex-col gap-0 overflow-hidden !p-0 sm:max-h-[min(48rem,calc(100dvh-3rem))]"
  >
    <div class="min-h-0 flex-1 overflow-y-auto px-5 pt-8 pb-6 sm:px-10 sm:pt-10 sm:pb-8">
      <Dialog.Title class="pb-1 text-xl font-semibold">{m.flow_create_dialog_title()}</Dialog.Title>
      <Dialog.Description class="text-secondary max-w-[60ch]">
        {mode === "prompt"
          ? m.flow_create_dialog_description()
          : m.flow_create_manual_description()}
      </Dialog.Description>

      {#if mode === "prompt"}
        <div class="mt-8 flex flex-col gap-2">
          <label for="flow-task-input" class="text-sm font-medium">
            {m.flow_create_prompt_label()}
          </label>
          <Textarea
            id="flow-task-input"
            bind:value={taskDescription}
            rows={5}
            class="field-sizing-fixed h-32 max-h-[min(20rem,40dvh)] resize-y overflow-y-auto"
            placeholder={m.flow_create_prompt_placeholder()}
          />
          <div class="mt-1 flex flex-wrap items-center gap-2">
            <span class="text-muted text-xs">{m.flow_create_examples_label()}</span>
            {#each taskExamples as example (example)}
              <Button
                variant="outline"
                size="xs"
                class="h-auto rounded-full px-3 py-1 whitespace-normal"
                onclick={() => {
                  taskDescription = example();
                }}
              >
                {example()}
              </Button>
            {/each}
          </div>
        </div>

        {#if canCreateFlowManually}
          <Separator class="mt-8 mb-4" />
          <p class="text-secondary text-sm">
            {m.flow_create_manual_more_control()}
            <Button
              variant="link"
              class="h-auto p-0 align-baseline"
              onclick={() => {
                mode = "manual";
              }}
            >
              {m.flow_create_configure_manually()}
            </Button>
          </p>
        {/if}
      {:else}
        <div class="mt-8 flex flex-col gap-2">
          <label for="flow-name-input" class="text-sm font-medium">{m.name()}</label>
          <Input
            id="flow-name-input"
            bind:value={newFlowName}
            placeholder={m.flow_create_name_placeholder()}
            required
          />
        </div>
      {/if}
      {#if createError}
        <p class="text-negative-stronger bg-negative-dimmer rounded-lg px-3 py-2 text-sm">
          {createError}
        </p>
      {/if}
    </div>

    <Dialog.Footer
      class="border-default bg-background !mx-0 !mb-0 shrink-0 rounded-b-xl border-t px-4 py-3 sm:px-6 sm:py-4"
    >
      {#if mode === "manual"}
        <label class="flex items-center gap-2 text-sm">
          <Switch bind:checked={openAfterCreation} size="sm" />
          {m.flow_create_open_editor_after()}
        </label>
        <div class="flex-grow"></div>
        {#if canUseAIBuilder}
          <Button
            variant="ghost"
            onclick={() => {
              mode = "prompt";
            }}>{m.go_back()}</Button
          >
        {/if}
        <Button
          variant="outline"
          class="w-full sm:w-auto"
          onclick={() => {
            showDialog = false;
            reset();
          }}>{m.cancel()}</Button
        >
        <Button class="w-full sm:w-auto" variant="default" onclick={createFlow}>
          {m.flow_create()}
        </Button>
      {:else}
        <div class="flex-grow"></div>
        <Button
          variant="outline"
          class="w-full sm:w-auto"
          onclick={() => {
            showDialog = false;
            reset();
          }}>{m.cancel()}</Button
        >
        <Button
          class="w-full sm:w-auto"
          variant="default"
          disabled={!taskDescription.trim()}
          onclick={continueToAIBuilder}
        >
          {m.flow_create_continue_ai()}
        </Button>
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
