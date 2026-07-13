<script lang="ts">
  import { untrack } from "svelte";
  import { resolve } from "$app/paths";
  import type { FlowSparse, Eneo } from "@eneo/eneo-js";
  import type { RecoverableAIBuilderDraftSession } from "$lib/features/flows/ai-builder/protocol";
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { initFlowsManager } from "$lib/features/flows/FlowsManager";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";
  import FlowsTable from "./FlowsTable.svelte";
  import CreateFlowDialog from "./CreateFlowDialog.svelte";
  import FlowPackageImportDialog from "$lib/features/flows/components/FlowPackageImportDialog.svelte";

  let {
    data
  }: {
    data: { flows: FlowSparse[]; eneo: Eneo; aiDrafts: RecoverableAIBuilderDraftSession[] };
  } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
  const { user } = getAppContext();

  // Flows manager consumes the initial data payload once; downstream reactivity lives
  // inside its own stores, so we untrack to silence the initial-reference warning.
  const {
    state: { flows }
  } = untrack(() =>
    initFlowsManager({
      flows: data.flows,
      spaceId: $currentSpace.id,
      eneo: data.eneo
    })
  );

  const countLabel = $derived.by(() => {
    const count = $flows.length;
    if (count === 0) return m.flow_list_count_zero();
    if (count === 1) return m.flow_list_count_singular();
    return m.flow_list_count_plural({ count: String(count) });
  });

  const draftTitles = $derived(
    data.aiDrafts
      .slice(0, 3)
      .map((draft) => draft.draft_title || m.ai_builder_draft_untitled())
      .join(" · ") + (data.aiDrafts.length > 3 ? " …" : "")
  );
</script>

<svelte:head>
  <title>Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {m.flows()}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.flows()}></Page.Title>
    {#if user.hasPermission("flows_manage")}
      <div class="flex items-center gap-2">
        <FlowPackageImportDialog
          eneo={data.eneo}
          spaceId={$currentSpace.id}
          spaceRouteId={$currentSpace.routeId}
        />
        <CreateFlowDialog />
      </div>
    {/if}
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-[1400px] flex-col gap-4 px-3 py-4 sm:px-6 sm:py-6">
      {#if data.aiDrafts.length > 0}
        <!-- In-progress AI drafts live on the builder page; without this strip
             the list page gives no way back to them. -->
        <a
          href={resolve(`/spaces/${$currentSpace.routeId}/flows/ai-builder`)}
          class="border-default bg-secondary/40 hover:bg-secondary/60 focus-visible:ring-accent-default/30 group flex items-center justify-between gap-4 rounded-lg border px-4 py-3 transition-colors focus-visible:ring-2 focus-visible:outline-none"
        >
          <span class="flex min-w-0 flex-col gap-0.5">
            <span class="text-primary text-sm font-medium">
              {m.ai_builder_drafts_strip_label({ count: String(data.aiDrafts.length) })}
            </span>
            <span class="text-secondary truncate text-xs">{draftTitles}</span>
          </span>
          <span
            class="text-accent-default shrink-0 text-sm font-medium group-hover:underline"
            aria-hidden="true"
          >
            {m.ai_builder_drafts_strip_continue()}
          </span>
        </a>
      {/if}
      <p class="text-muted text-xs font-medium tracking-wide uppercase" aria-live="polite">
        {countLabel}
      </p>
      <FlowsTable flows={$flows} />
    </div>
  </Page.Main>
</Page.Root>
