<script lang="ts">
  import { goto } from "$app/navigation";
  import { getAppContext } from "$lib/core/AppContext";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getFlowsManager } from "$lib/features/flows/FlowsManager";
  import { IconWorkflow } from "@intric/icons/workflow";
  import { IntricError } from "@intric/intric-js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace }
  } = getSpacesManager();
  const { user } = getAppContext();

  const flowsManager = getFlowsManager();
  const showDialog = writable(false);
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

  function openDialog() {
    reset();
    if (!canCreateFlowManually && canUseAIBuilder) {
      goToAIBuilder();
      return;
    }
    $showDialog = true;
  }

  function goToAIBuilder() {
    $showDialog = false;
    reset();
    goto(`/spaces/${$currentSpace.routeId}/flows/ai-builder`);
  }

  async function createFlow() {
    try {
      const created = await flowsManager.createFlow(newFlowName);
      if (openAfterCreation && created.id) {
        goto(`/spaces/${$currentSpace.routeId}/flows/${created.id}`);
      }
      newFlowName = "";
      $showDialog = false;
      reset();
    } catch (error) {
      createError = error instanceof IntricError ? error.getReadableMessage() : String(error);
    }
  }
</script>

<Button variant="primary" onclick={openDialog}>
  <IconWorkflow size="sm" />
  {m.flow_create()}
</Button>

<Dialog.Root openController={showDialog}>
  <Dialog.Content width="dynamic">
    <Dialog.Section class="relative mt-2 -mb-0.5">
      <div class="border-default flex w-full flex-col px-10 pt-12 pb-10">
        <h3 class="px-4 pb-1 text-2xl font-extrabold">{m.flow_create()}</h3>
        <p class="text-secondary max-w-[60ch] pr-36 pl-4">
          {m.flow_empty_description()}
        </p>

        {#if mode === "choose"}
          <!-- Two option cards -->
          <div class="mt-10 grid gap-4 px-4" class:grid-cols-2={canCreateFlowManually && canUseAIBuilder}>
            <!-- Build with AI card -->
            {#if canUseAIBuilder}
              <button
                type="button"
                class="ai-card group relative flex cursor-pointer flex-col rounded-xl p-5 text-left transition-all hover:scale-[1.02]"
                onclick={goToAIBuilder}
              >
                <div class="ai-card-icon mb-3">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="size-7">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 0 0-2.455 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z" />
                  </svg>
                </div>
                <span class="text-primary text-base font-semibold">{m.ai_builder_create_with_ai()}</span>
                <span class="text-secondary mt-1 text-sm">{m.ai_builder_create_with_ai_description()}</span>
              </button>
            {/if}

            <!-- Build manually card -->
            {#if canCreateFlowManually}
              <button
                type="button"
                class="manual-card group flex cursor-pointer flex-col rounded-xl border border-transparent p-5 text-left transition-all hover:scale-[1.02]"
                onclick={(e) => {
                  e.preventDefault();
                  mode = "manual";
                }}
              >
                <div class="text-muted mb-3 transition-colors group-hover:text-primary">
                  <IconWorkflow class="size-7" />
                </div>
                <span class="text-primary text-base font-semibold">{m.ai_builder_create_manually()}</span>
                <span class="text-secondary mt-1 text-sm">{m.ai_builder_create_manually_description()}</span>
              </button>
            {/if}
          </div>
        {:else}
          <!-- Manual creation form -->
          <div class="border-dimmer mt-14 mb-4 border-t"></div>
          <div class="flex flex-col gap-1 pt-6 pb-4">
            <span class="px-4 pb-1 text-lg font-medium">{m.name()}</span>
            <Input.Text
              bind:value={newFlowName}
              hiddenLabel
              inputClass="!text-lg !py-6 !px-4"
              placeholder={m.flow_create_name_placeholder()}
              required>{m.name()}</Input.Text
            >
          </div>
        {/if}
      </div>
    </Dialog.Section>

    {#if createError}
      <Dialog.Section>
        <p class="text-negative-stronger bg-negative-dimmer mx-4 rounded-lg px-3 py-2 text-sm">
          {createError}
        </p>
      </Dialog.Section>
    {/if}

    <Dialog.Controls let:close>
      {#if mode === "manual"}
        <Input.Switch bind:value={openAfterCreation} class="flex-row-reverse p-2">
          {m.flow_create_open_editor_after()}
        </Input.Switch>
        <div class="flex-grow"></div>
        <Button is={close} onclick={reset}>{m.cancel()}</Button>
        <Button is={close} onclick={createFlow} variant="primary">{m.flow_create()}</Button>
      {:else}
        <div class="flex-grow"></div>
        <Button is={close} onclick={reset}>{m.cancel()}</Button>
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<style lang="postcss">
  @reference "@intric/ui/styles";

  .ai-card {
    background: oklch(from var(--accent-default) l c h / 0.05);
    border: 1px solid oklch(from var(--accent-default) l c h / 0.15);
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  }
  
  .ai-card:hover {
    background: oklch(from var(--accent-default) l c h / 0.1);
    border-color: oklch(from var(--accent-default) l c h / 0.25);
    box-shadow: 0 4px 12px -4px oklch(from var(--accent-default) l c h / 0.2);
  }
  
  .ai-card-icon {
    color: var(--accent-default);
  }

  .manual-card {
    background: var(--bg-secondary);
    border-color: var(--border-default);
  }

  .manual-card:hover {
    background: var(--bg-hover-dimmer);
    border-color: var(--border-stronger);
    box-shadow: 0 4px 12px -4px oklch(0 0 0 / 0.05);
  }
</style>
