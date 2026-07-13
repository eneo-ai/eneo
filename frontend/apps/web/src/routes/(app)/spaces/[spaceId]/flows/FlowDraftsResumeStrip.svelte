<script lang="ts">
  import { resolve } from "$app/paths";
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
  <a
    href={resolve(`/spaces/${spaceRouteId}/flows/ai-builder`)}
    class="border-default bg-secondary/40 hover:bg-secondary/60 focus-visible:ring-accent-default/30 group flex items-center justify-between gap-4 rounded-lg border px-4 py-3 transition-colors focus-visible:ring-2 focus-visible:outline-none"
  >
    <span class="flex min-w-0 flex-col gap-0.5">
      <span class="text-primary text-sm font-medium">
        {m.ai_builder_drafts_strip_label({ count: String(drafts.length) })}
      </span>
      <span class="text-secondary truncate text-xs">{titles}</span>
    </span>
    <span
      class="text-accent-default shrink-0 text-sm font-medium group-hover:underline"
      aria-hidden="true"
    >
      {m.ai_builder_drafts_strip_continue()}
    </span>
  </a>
{/if}
