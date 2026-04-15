<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { getAppContext } from "$lib/core/AppContext";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getFlowsManager } from "$lib/features/flows/FlowsManager";
  import { IconWorkflow } from "@intric/icons/workflow";
  import { IntricError } from "@intric/intric-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
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

  let mode = $state<"choose" | "manual">("choose");
  let newFlowName = $state("");
  let openAfterCreation = $state(true);
  let createError = $state<string | null>(null);

  function reset() {
    mode = canCreateFlowManually && !canUseAIBuilder ? "manual" : "choose";
    newFlowName = "";
  }

  function openCreateDialog() {
    reset();
    if (!canCreateFlowManually && canUseAIBuilder) {
      goToAIBuilder();
      return;
    }
    showDialog = true;
  }

  function goToAIBuilder() {
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
      createError = error instanceof IntricError ? error.getReadableMessage() : String(error);
    }
  }
</script>

<Button variant="default" onclick={openCreateDialog}>
  <IconWorkflow class="size-4" />
  {m.flow_create()}
</Button>

<Dialog.Root bind:open={showDialog}>
  <Dialog.Content class="!max-w-2xl !p-0">
    <div class="relative px-10 pt-12 pb-10">
      <Dialog.Title class="px-4 pb-1 text-2xl font-extrabold">{m.flow_create()}</Dialog.Title>
      <Dialog.Description class="text-secondary max-w-[60ch] pr-36 pl-4">
        {m.flow_empty_description()}
      </Dialog.Description>

      {#if mode === "choose"}
        <!-- Two option cards -->
        <div
          class="mt-10 grid gap-4 px-4"
          class:grid-cols-2={canCreateFlowManually && canUseAIBuilder}
        >
          <!-- Build with AI card -->
          {#if canUseAIBuilder}
            <button
              type="button"
              class="group border-accent-default/15 bg-accent-default/5 hover:border-accent-default/25 hover:bg-accent-default/10 relative flex cursor-pointer flex-col rounded-xl border p-5 text-left transition-all duration-200 hover:scale-[1.02] hover:shadow-md"
              onclick={goToAIBuilder}
            >
              <div class="text-accent-default mb-3">
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.5"
                  class="size-7"
                >
                  <path
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 0 0-2.455 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z"
                  />
                </svg>
              </div>
              <span class="text-primary text-base font-semibold"
                >{m.ai_builder_create_with_ai()}</span
              >
              <span class="text-secondary mt-1 text-sm"
                >{m.ai_builder_create_with_ai_description()}</span
              >
            </button>
          {/if}

          <!-- Build manually card -->
          {#if canCreateFlowManually}
            <button
              type="button"
              class="group border-default bg-secondary hover:border-stronger hover:bg-hover-dimmer flex cursor-pointer flex-col rounded-xl border p-5 text-left transition-all duration-200 hover:scale-[1.02] hover:shadow-md"
              onclick={(e) => {
                e.preventDefault();
                mode = "manual";
              }}
            >
              <div class="text-muted group-hover:text-primary mb-3 transition-colors">
                <IconWorkflow class="size-7" />
              </div>
              <span class="text-primary text-base font-semibold"
                >{m.ai_builder_create_manually()}</span
              >
              <span class="text-secondary mt-1 text-sm"
                >{m.ai_builder_create_manually_description()}</span
              >
            </button>
          {/if}
        </div>
      {:else}
        <!-- Manual creation form -->
        <Separator class="mt-14 mb-4" />
        <div class="flex flex-col gap-1 pt-6 pb-4">
          <label for="flow-name-input" class="px-4 pb-1 text-lg font-medium">{m.name()}</label>
          <Input
            id="flow-name-input"
            bind:value={newFlowName}
            class="!px-4 !py-6 !text-lg"
            placeholder={m.flow_create_name_placeholder()}
            required
          />
        </div>
      {/if}
    </div>

    {#if createError}
      <div class="px-4 pb-4">
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
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
