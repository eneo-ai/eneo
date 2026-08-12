<script lang="ts">
  import { resolve } from "$app/paths";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { RecoverableAIBuilderDraftSession } from "$lib/features/flows/ai-builder/protocol";

  interface Props {
    drafts: RecoverableAIBuilderDraftSession[];
    /** Route id of the space whose AI-builder page owns resume/choose. */
    spaceRouteId: string;
  }

  let { drafts, spaceRouteId }: Props = $props();

  const titles = $derived(
    drafts
      .slice(0, 3)
      .map((draft) => draft.draft_title || m.ai_builder_draft_untitled())
      .join(" · ") + (drafts.length > 3 ? " …" : "")
  );
</script>

{#if drafts.length > 0}
  <!-- In-progress AI drafts live on the builder page; without this strip the
       list page gives no way back to them. -->
  <Card.Root
    class="bg-secondary/40 flex-row items-center justify-between gap-4 px-4 py-3 max-sm:flex-col max-sm:items-stretch"
  >
    <span class="flex min-w-0 flex-col gap-0.5">
      <span class="text-primary text-sm font-medium">
        {m.ai_builder_drafts_strip_label({ count: String(drafts.length) })}
      </span>
      <span class="text-secondary truncate text-xs">{titles}</span>
    </span>
    <Button
      href={resolve(`/spaces/${spaceRouteId}/flows/ai-builder`)}
      variant="outline"
      size="sm"
      class="max-sm:w-full"
    >
      {m.ai_builder_view_drafts({ count: String(drafts.length) })}
    </Button>
  </Card.Root>
{/if}
