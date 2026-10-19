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

  type CountNote = Exclude<AIBuilderCoverageNote, { kind: "tool_catalog_unavailable" }>;
  type CountLabel = (count: number) => string;
  const OMITTED: Record<CountNote["material"], CountLabel> = {
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
        : m.ai_builder_coverage_classification_sources_omitted({ count: String(count) }),
    attachment_files: (count) =>
      count === 1
        ? m.ai_builder_coverage_attachment_files_omitted_one()
        : m.ai_builder_coverage_attachment_files_omitted({ count: String(count) }),
    run_excerpts: (count) =>
      count === 1
        ? m.ai_builder_coverage_run_excerpts_omitted_one()
        : m.ai_builder_coverage_run_excerpts_omitted({ count: String(count) }),
    usable_tools: (count) =>
      count === 1
        ? m.ai_builder_coverage_usable_tools_omitted_one()
        : m.ai_builder_coverage_usable_tools_omitted({ count: String(count) }),
    tool_schemas: (count) =>
      count === 1
        ? m.ai_builder_coverage_tool_schemas_omitted_one()
        : m.ai_builder_coverage_tool_schemas_omitted({ count: String(count) }),
    unavailable_tool_names: (count) =>
      count === 1
        ? m.ai_builder_coverage_unavailable_tool_names_omitted_one()
        : m.ai_builder_coverage_unavailable_tool_names_omitted({ count: String(count) })
  };
  // Only the reading's fit and answer limit, the attachment fits and the
  // run-excerpt fit shorten an item; the other materials are left out whole.
  const SHORTENED: Partial<Record<CountNote["material"], CountLabel>> = {
    classification_sources: (count) =>
      count === 1
        ? m.ai_builder_coverage_classification_sources_shortened_one()
        : m.ai_builder_coverage_classification_sources_shortened({ count: String(count) }),
    attachment_files: (count) =>
      count === 1
        ? m.ai_builder_coverage_attachment_files_shortened_one()
        : m.ai_builder_coverage_attachment_files_shortened({ count: String(count) }),
    run_excerpts: (count) =>
      count === 1
        ? m.ai_builder_coverage_run_excerpts_shortened_one()
        : m.ai_builder_coverage_run_excerpts_shortened({ count: String(count) })
  };

  function parts(note: AIBuilderCoverageNote): string[] {
    if (note.kind === "tool_catalog_unavailable") {
      return [m.ai_builder_coverage_tool_catalog_unavailable()];
    }
    const shortened = SHORTENED[note.material];
    return [
      ...(note.omitted > 0 ? [OMITTED[note.material](note.omitted)] : []),
      ...(note.shortened > 0 && shortened ? [shortened(note.shortened)] : [])
    ];
  }

  // Omitted items weigh before shortened ones.
  function leftOutMore(note: AIBuilderCoverageNote, than: AIBuilderCoverageNote): boolean {
    if (note.kind === "tool_catalog_unavailable" || than.kind === "tool_catalog_unavailable") {
      return false;
    }
    return (
      note.omitted > than.omitted ||
      (note.omitted === than.omitted && note.shortened > than.shortened)
    );
  }

  // A note with nothing this client can name (only shortened items of a
  // material it has no shortened words for) is left out, never an empty line.
  const shown = $derived(coverage.notes.filter((note) => parts(note).length > 0));
  // The line names each material once, by the stage that left out the most;
  // the popover keeps every stage.
  const line = $derived.by(() => {
    const worst: Partial<Record<AIBuilderCoverageNote["material"], AIBuilderCoverageNote>> = {};
    for (const note of shown) {
      const kept = worst[note.material];
      if (!kept || leftOutMore(note, kept)) worst[note.material] = note;
    }
    return m.ai_builder_coverage_line({
      parts: formatList(
        Object.values(worst).flatMap((note) => (note ? parts(note).slice(0, 1) : []))
      )
    });
  });
</script>

{#if shown.length > 0}
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
        {#each shown as note (`${note.stage}:${note.material}`)}
          <li class="flex flex-col gap-0.5 text-xs leading-relaxed">
            <span class="text-primary font-semibold">
              {note.stage === "classification"
                ? m.ai_builder_coverage_stage_classification()
                : m.ai_builder_coverage_stage_proposal()}
            </span>
            {#if note.kind === "tool_catalog_unavailable"}
              <span class="text-secondary">
                {m.ai_builder_coverage_tool_catalog_unavailable_detail()}
              </span>
            {:else}
              <span class="text-secondary">
                {m.ai_builder_coverage_note_detail({
                  parts: formatList(parts(note)),
                  total: String(note.total)
                })}
              </span>
              {#if note.reasons.includes("fixed_limit")}
                <span class="text-secondary">{m.ai_builder_coverage_fixed_limit_reason()}</span>
              {/if}
              {#if note.reasons.includes("configured_limit")}
                <span class="text-secondary">{m.ai_builder_coverage_configured_limit_reason()}</span
                >
              {/if}
              {#if note.reasons.includes("model_room")}
                <span class="text-secondary">{m.ai_builder_coverage_model_room_hint()}</span>
              {/if}
            {/if}
          </li>
        {/each}
      </ul>
    </Popover.Content>
  </Popover.Root>
{/if}
