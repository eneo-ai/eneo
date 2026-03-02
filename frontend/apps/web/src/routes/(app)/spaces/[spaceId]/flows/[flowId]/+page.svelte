<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { initFlowEditor } from "$lib/features/flows/FlowEditor";
  import { initFlowUserMode, getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import FlowStepList from "$lib/features/flows/components/FlowStepList.svelte";
  import FlowStepEditPanel from "$lib/features/flows/components/FlowStepEditPanel.svelte";
  import FlowGraphPanel from "$lib/features/flows/components/FlowGraphPanel.svelte";
  import FlowUserModeToggle from "$lib/features/flows/components/FlowUserModeToggle.svelte";
  import FlowSaveStatus from "$lib/features/flows/components/FlowSaveStatus.svelte";
  import FlowVersionBadge from "$lib/features/flows/components/FlowVersionBadge.svelte";
  import FlowValidationBanner from "$lib/features/flows/components/FlowValidationBanner.svelte";
  import FlowRunsTable from "$lib/features/flows/components/FlowRunsTable.svelte";
  import FlowRunDialog from "$lib/features/flows/components/FlowRunDialog.svelte";
  import { Button } from "@intric/ui";
  import { IntricError } from "@intric/intric-js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { onDestroy } from "svelte";

  export let data;
  let publishLoading = false;
  let showRunDialog = false;
  let runsReloadTrigger = 0;

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const userMode = initFlowUserMode();

  const flowEditor = initFlowEditor({
    flow: data.flow,
    intric: data.intric
  });

  const {
    state: { resource, update, activeStepId, isPublished, saveStatus, validationErrors }
  } = flowEditor;

  $: canPublish = !$isPublished && $saveStatus === "saved" && $validationErrors.size === 0;

  onDestroy(() => {
    flowEditor.destroy();
  });

  let activeTab: "builder" | "history" = "builder";
</script>

<svelte:head>
  <title>Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {$resource.name}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      truncate={true}
      parent={{ href: `/spaces/${$currentSpace.routeId}/flows` }}
      title={$resource.name}
    >
    </Page.Title>

    <Page.Tabbar>
      <div role="tablist" class="flex">
        <button
          role="tab"
          aria-selected={activeTab === "builder"}
          aria-controls="panel-builder"
          class="border-b-[3px] px-4 py-2 text-sm font-medium transition-colors duration-200"
          class:border-blue-500={activeTab === "builder"}
          class:text-primary={activeTab === "builder"}
          class:border-transparent={activeTab !== "builder"}
          class:text-secondary={activeTab !== "builder"}
          on:click={() => (activeTab = "builder")}
        >
          {m.flow_builder()}
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "history"}
          aria-controls="panel-history"
          class="border-b-[3px] px-4 py-2 text-sm font-medium transition-colors duration-200"
          class:border-blue-500={activeTab === "history"}
          class:text-primary={activeTab === "history"}
          class:border-transparent={activeTab !== "history"}
          class:text-secondary={activeTab !== "history"}
          on:click={() => (activeTab = "history")}
        >
          {m.flow_history()}
        </button>
      </div>
    </Page.Tabbar>

    <Page.Flex>
      <FlowVersionBadge publishedVersion={$resource.published_version} />
      <FlowSaveStatus status={$saveStatus} />
      <FlowUserModeToggle />
      {#if $isPublished}
        <Button variant="primary" on:click={() => { showRunDialog = true; }}>
          {m.flow_run_trigger()}
        </Button>
        <Button variant="destructive" disabled={publishLoading} on:click={async () => {
          publishLoading = true;
          try {
            const updated = await data.intric.flows.unpublish({ id: $resource.id });
            flowEditor.setResource(updated);
          } catch (e) {
            const msg = e instanceof IntricError ? e.getReadableMessage() : String(e);
            console.error("Unpublish failed:", msg);
            toast.error(msg);
          } finally {
            publishLoading = false;
          }
        }}>{m.flow_unpublish_to_edit()}</Button>
      {:else}
        <Button variant="primary" disabled={!canPublish || publishLoading} on:click={async () => {
          publishLoading = true;
          try {
            const published = await data.intric.flows.publish({ id: $resource.id });
            flowEditor.setResource(published);
          } catch (e) {
            const msg = e instanceof IntricError ? e.getReadableMessage() : String(e);
            console.error("Publish failed:", msg);
            toast.error(msg);
          } finally {
            publishLoading = false;
          }
        }}>{m.flow_publish()}</Button>
      {/if}
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <div id="panel-builder" role="tabpanel" class="flex flex-1 flex-col overflow-hidden" class:hidden={activeTab !== "builder"}>
      {#if $isPublished}
        <div class="bg-amber-50 border-amber-200 text-amber-800 border-b px-4 py-2 text-sm">
          {m.flow_published_readonly()}
        </div>
      {/if}
      <FlowValidationBanner errors={$validationErrors} />

      <div class="flex flex-1 flex-col overflow-hidden lg:flex-row">
        <!-- Step list: sidebar on desktop, horizontal on mobile -->
        <div class="border-default hidden shrink-0 overflow-y-auto border-r lg:flex lg:w-[280px] lg:flex-col">
          <FlowStepList
            steps={$update.steps}
            activeStepId={$activeStepId}
            isPublished={$isPublished}
            on:selectStep={(e) => activeStepId.set(e.detail)}
            on:stepsChanged={(e) => {
              $update.steps = e.detail;
            }}
          />
        </div>

        <!-- Compact step selector for mobile/tablet -->
        <div class="border-default flex items-center gap-2 overflow-x-auto border-b px-3 py-2 lg:hidden">
          {#each $update.steps ?? [] as step (step.id ?? step.step_order)}
            <button
              class="shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors"
              class:bg-blue-100={$activeStepId === step.id}
              class:text-blue-700={$activeStepId === step.id}
              class:bg-hover-dimmer={$activeStepId !== step.id}
              class:text-secondary={$activeStepId !== step.id}
              on:click={() => activeStepId.set(step.id ?? null)}
            >
              {step.step_order}. {(step.user_description || "Step").slice(0, 16)}
            </button>
          {/each}
          {#if !$isPublished}
            <button
              class="hover:bg-hover-dimmer shrink-0 rounded-full px-3 py-1.5 text-xs font-medium text-blue-600 transition-colors"
              on:click={() => flowEditor.addStep()}
            >+ {m.flow_step_add()}</button>
          {/if}
        </div>

        <!-- Step inspector (right, flex-grow) -->
        <div class="flex flex-1 flex-col overflow-hidden">
          <div class="flex-1 overflow-y-auto">
            <FlowStepEditPanel
              steps={$update.steps}
              activeStepId={$activeStepId}
              isPublished={$isPublished}
              formSchema={$update.metadata_json?.form_schema as { fields: { name: string; type: string; required?: boolean }[] } | undefined}
              on:stepChanged={(e) => {
                const { index, step } = e.detail;
                $update.steps[index] = step;
                $update.steps = $update.steps;
              }}
              on:removeStep={(e) => {
                const idx = e.detail;
                $update.steps = $update.steps.filter((_, i) => i !== idx);
                $update.steps.forEach((s, i) => { s.step_order = i + 1; });
                // Step at position 1 cannot use previous_step/all_previous_steps
                if ($update.steps[0] && ($update.steps[0].input_source === "previous_step" || $update.steps[0].input_source === "all_previous_steps")) {
                  $update.steps[0] = { ...$update.steps[0], input_source: "flow_input" };
                }
                $update.steps = $update.steps;
                activeStepId.set(null);
              }}
            />
          </div>

          <!-- Graph preview (bottom, collapsible) -->
          <FlowGraphPanel
            flow={$update}
            activeStepId={$activeStepId}
            on:nodeClick={(e) => activeStepId.set(e.detail)}
          />
        </div>
      </div>
    </div>

    <div id="panel-history" role="tabpanel" class="flex-1 overflow-y-auto" class:hidden={activeTab !== "history"}>
      <FlowRunsTable flow={$resource} intric={data.intric} visible={activeTab === "history"} reloadTrigger={runsReloadTrigger} />
    </div>
  </Page.Main>
</Page.Root>

<FlowRunDialog
  bind:open={showRunDialog}
  flow={$resource}
  intric={data.intric}
  lastInputPayload={null}
  on:runCreated={() => {
    activeTab = "history";
    runsReloadTrigger++;
  }}
/>

<style>
  @media (prefers-reduced-motion: reduce) {
    :global(*),
    :global(*::before),
    :global(*::after) {
      animation-duration: 0.01ms !important;
      transition-duration: 0.01ms !important;
    }
  }
</style>
