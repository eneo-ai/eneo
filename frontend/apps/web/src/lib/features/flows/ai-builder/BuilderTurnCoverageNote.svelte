<script lang="ts">
  import Info from "@lucide/svelte/icons/info";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { formatList } from "$lib/core/formatting/formatList";
  import { m } from "$lib/paraglide/messages";
  import type { AIBuilderCoverageNote, AIBuilderTurnCoverage } from "./protocol";

  interface Props {
    /** What the turn's sent model requests left out of the user's material. */
    coverage: AIBuilderTurnCoverage;
  }

  let { coverage }: Props = $props();

  type CountLabel = (count: number) => string;
  const OMITTED: Record<AIBuilderCoverageNote["material"], CountLabel> = {
    history_messages: (count) =>
      count === 1
        ? m.ai_builder_coverage_history_messages_omitted_one()
        : m.ai_builder_coverage_history_messages_omitted({ count: String(count) }),
    requirement_assumptions: (count) =>
      count === 1
        ? m.ai_builder_coverage_requirement_assumptions_omitted_one()
        : m.ai_builder_coverage_requirement_assumptions_omitted({ count: String(count) }),
    classification_sources: (count) =>
      count === 1
        ? m.ai_builder_coverage_classification_sources_omitted_one()
        : m.ai_builder_coverage_classification_sources_omitted({ count: String(count) })
  };
  // Only the reading's fit and answer limit shorten an item; the proposal
  // evicts history and assumptions whole.
  const SHORTENED: Partial<Record<AIBuilderCoverageNote["material"], CountLabel>> = {
    classification_sources: (count) =>
      count === 1
        ? m.ai_builder_coverage_classification_sources_shortened_one()
        : m.ai_builder_coverage_classification_sources_shortened({ count: String(count) })
  };

  function parts(note: AIBuilderCoverageNote): string[] {
    const shortened = SHORTENED[note.material];
    return [
      ...(note.omitted > 0 ? [OMITTED[note.material](note.omitted)] : []),
      ...(note.shortened > 0 && shortened ? [shortened(note.shortened)] : [])
    ];
  }

  const line = $derived(
    m.ai_builder_coverage_line({ parts: formatList(coverage.notes.flatMap(parts)) })
  );
</script>

<Popover.Root>
  <Popover.Trigger>
    {#snippet child({ props })}
      <Button
        {...props}
        variant="ghost"
        size="xs"
        class="text-secondary h-auto max-w-full py-0.5 font-normal whitespace-normal"
      >
        <Info data-icon="inline-start" aria-hidden="true" />
        <span class="text-left">{line}</span>
      </Button>
    {/snippet}
  </Popover.Trigger>
  <Popover.Content align="end" class="w-80">
    <Popover.Header>
      <Popover.Title>{m.ai_builder_coverage_popover_title()}</Popover.Title>
    </Popover.Header>
    <ul class="flex list-none flex-col gap-2.5 p-0">
      {#each coverage.notes as note (`${note.stage}:${note.material}`)}
        <li class="flex flex-col gap-0.5 text-xs leading-relaxed">
          <span class="text-primary font-semibold">
            {note.stage === "classification"
              ? m.ai_builder_coverage_stage_classification()
              : m.ai_builder_coverage_stage_proposal()}
          </span>
          <span class="text-secondary">
            {m.ai_builder_coverage_note_detail({
              parts: formatList(parts(note)),
              total: String(note.total)
            })}
          </span>
          {#if note.reasons.includes("fixed_limit")}
            <span class="text-secondary">{m.ai_builder_coverage_fixed_limit_reason()}</span>
          {/if}
          {#if note.reasons.includes("model_room")}
            <span class="text-secondary">{m.ai_builder_coverage_model_room_hint()}</span>
          {/if}
        </li>
      {/each}
    </ul>
  </Popover.Content>
</Popover.Root>
