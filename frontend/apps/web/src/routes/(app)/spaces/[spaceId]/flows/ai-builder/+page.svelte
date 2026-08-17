<script lang="ts">
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { page } from "$app/state";
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import FlowAIBuilder from "$lib/features/flows/ai-builder/FlowAIBuilder.svelte";
  import BuilderSessionStatus from "$lib/features/flows/ai-builder/BuilderSessionStatus.svelte";
  import { initAIBuilderService } from "$lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts";
  import { m } from "$lib/paraglide/messages";
  import { onDestroy, untrack } from "svelte";

  let { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const aiBuilderService = untrack(() => initAIBuilderService(data.eneo, $currentSpace.id, null));

  // A draft chosen in the Flöden list arrives as ?session=<id>; read once at mount.
  const resumeSessionId = untrack(() => page.url.searchParams.get("session"));

  onDestroy(() => {
    aiBuilderService.destroy();
  });
</script>

<svelte:head>
  <title
    >Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {m.ai_builder_tab()}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      truncate={true}
      parent={{ href: `/spaces/${$currentSpace.routeId}/flows` }}
      title={m.ai_builder_tab()}
    ></Page.Title>
    <!-- The design keeps the saved state and the way into the conversation on
         the title row, so the phase rail is the only thing above the work. -->
    <BuilderSessionStatus />
  </Page.Header>

  <Page.Main>
    <div class="flex flex-1 flex-col overflow-hidden">
      <FlowAIBuilder
        targetKind="create"
        statusInPageHeader
        {resumeSessionId}
        onapplied={async (detail) => {
          goto(resolve(`/spaces/${$currentSpace.routeId}/flows/${detail.flow_id}`));
        }}
      />
    </div>
  </Page.Main>
</Page.Root>
