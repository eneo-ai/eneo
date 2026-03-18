<script lang="ts">
  import { goto } from "$app/navigation";
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import FlowAIBuilder from "$lib/features/flows/ai-builder/FlowAIBuilder.svelte";
  import { initAIBuilderService } from "$lib/features/flows/ai-builder/FlowAIBuilderService.svelte.ts";
  import { m } from "$lib/paraglide/messages";
  import { onDestroy } from "svelte";

  let { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const aiBuilderService = initAIBuilderService(data.intric, $currentSpace.id, null);

  onDestroy(() => {
    aiBuilderService.destroy();
  });
</script>

<svelte:head>
  <title>Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {m.ai_builder_tab()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      truncate={true}
      parent={{ href: `/spaces/${$currentSpace.routeId}/flows` }}
      title={m.ai_builder_tab()}
    ></Page.Title>
  </Page.Header>

  <Page.Main>
    <div class="flex flex-1 flex-col overflow-hidden">
      <FlowAIBuilder
        targetKind="create"
        onapplied={async (detail) => {
          goto(`/spaces/${$currentSpace.routeId}/flows/${detail.flow_id}`);
        }}
      />
    </div>
  </Page.Main>
</Page.Root>
