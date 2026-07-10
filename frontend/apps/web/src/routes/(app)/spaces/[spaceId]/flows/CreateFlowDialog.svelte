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
  <Dialog.Content class="!max-w-2xl !p-0">
    <div class="px-8 pt-10 pb-8 sm:px-10">
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
            rows={3}
            placeholder={m.flow_create_prompt_placeholder()}
          />
          <div class="mt-1 flex flex-wrap items-center gap-2">
            <span class="text-muted text-xs">{m.flow_create_examples_label()}</span>
            {#each taskExamples as example (example)}
              <button
                type="button"
                class="border-default text-secondary hover:border-stronger hover:text-primary focus-visible:ring-accent-default/40 rounded-full border px-3 py-1 text-xs transition-colors focus-visible:ring-2 focus-visible:outline-none"
                onclick={() => {
                  taskDescription = example();
                }}
              >
                {example()}
              </button>
            {/each}
          </div>
        </div>

        {#if canCreateFlowManually}
          <Separator class="mt-8 mb-4" />
          <p class="text-secondary text-sm">
            {m.flow_create_manual_more_control()}
            <button
              type="button"
              class="text-accent-default hover:text-accent-stronger font-medium underline-offset-2 hover:underline"
              onclick={() => {
                mode = "manual";
              }}
            >
              {m.flow_create_configure_manually()}
            </button>
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
    </div>

    {#if createError}
      <div class="px-8 pb-4 sm:px-10">
        <p class="text-negative-stronger bg-negative-dimmer rounded-lg px-3 py-2 text-sm">
          {createError}
        </p>
      </div>
    {/if}

    <Dialog.Footer class="border-default bg-background !mx-0 !mb-0 rounded-b-xl border-t px-6 py-4">
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
          onclick={() => {
            showDialog = false;
            reset();
          }}>{m.cancel()}</Button
        >
        <Button variant="default" onclick={createFlow}>{m.flow_create()}</Button>
      {:else}
        <div class="flex-grow"></div>
        <Button
          variant="outline"
          onclick={() => {
            showDialog = false;
            reset();
          }}>{m.cancel()}</Button
        >
        <Button variant="default" disabled={!taskDescription.trim()} onclick={continueToAIBuilder}>
          {m.flow_create_continue_ai()}
        </Button>
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
