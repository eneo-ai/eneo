<script lang="ts">
  import { countMessage } from "$lib/features/flows/flowCount";
  import { SvelteSet } from "svelte/reactivity";
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import IconHeadphones from "@lucide/svelte/icons/headphones";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as m from "$lib/paraglide/messages";
  import {
    keptProposal,
    withProposalSupport,
    type SpeakerMappingRow
  } from "../speakerMappingReview";
  import { speakerColorIndex } from "../transcriptSegments";
  let {
    rows,
    proposed,
    participants,
    inferred = false,
    disabled = false,
    onChange,
    onListen,
    sampleAvailable = () => false
  }: {
    rows: SpeakerMappingRow[];
    /** The step's own rows: the names it proposed, with its confidence and evidence. */
    proposed: SpeakerMappingRow[];
    participants: string[];
    inferred?: boolean;
    disabled?: boolean;
    onChange: (rows: SpeakerMappingRow[]) => void;
    onListen?: (label: string) => void;
    sampleAvailable?: (label: string) => boolean;
  } = $props();
  const id = $props.id();
  const names = $derived([
    ...new Set([
      ...participants,
      ...rows.map((r) => r.name?.trim()).filter((n): n is string => !!n)
    ])
  ]);
  const summary = $derived(
    rows
      .map((r, i) => r.name?.trim() || m.flow_transcript_editor_speaker({ number: i + 1 }))
      .join(", ")
  );
  const colors = [
    "accent-stronger",
    "positive-stronger",
    "warning-stronger",
    "negative-stronger",
    "label-stronger",
    "dynamic-stronger",
    "accent-stronger",
    "positive-stronger"
  ];

  // One disclosure per row: a single flag would open every row at once.
  const whyOpen = new SvelteSet<string>();

  /** The step's proposal beside the name it proposed: how sure it was, or that it had none. */
  function proposalNote(row: SpeakerMappingRow): string {
    if (!row.name) return ` · ${m.flow_transcript_editor_no_suggestion()}`;
    const confidence =
      row.confidence === "high"
        ? m.flow_transcript_editor_confidence_high()
        : row.confidence === "medium"
          ? m.flow_transcript_editor_confidence_medium()
          : m.flow_transcript_editor_confidence_low();
    const fromConversation =
      inferred && !participants.includes(row.name) ? m.flow_transcript_editor_inferred_name() : "";
    return ` · ${m.flow_transcript_editor_confidence({ confidence })}${fromConversation}`;
  }
</script>

<details class="border-default bg-primary min-w-0 rounded-xl border p-4" open>
  <summary
    class="text-primary focus-visible:ring-ring cursor-pointer text-sm font-medium focus-visible:ring-2"
  >
    {m.flow_transcript_editor_speakers()}
    <span class="text-muted ml-2 font-normal [overflow-wrap:anywhere]">{summary}</span>
  </summary>
  <p class="text-muted mt-2 text-xs leading-relaxed">
    {m.flow_transcript_editor_naming_hint()}
  </p>
  <datalist {id}
    >{#each names as name (name)}<option value={name}></option>{/each}</datalist
  >
  {#each rows as row, index (row.label)}
    <!-- Only the name the step proposed is its proposal: a name a person gave
         or cleared is theirs, with none of the step's wording or reasoning. -->
    {@const asProposed = keptProposal(row, proposed) !== undefined}
    <div
      class="border-default grid min-w-0 grid-cols-[5.5rem_minmax(0,1fr)_2.5rem] items-start gap-3 border-b py-5 last:border-b-0"
    >
      <label
        for={id + "-" + index}
        class="pt-2 text-xs font-medium"
        style:color={"var(--" + colors[speakerColorIndex(row.label) % colors.length] + ")"}
        >● {m.flow_transcript_editor_speaker({ number: index + 1 })}</label
      >
      <div class="min-w-0">
        <Input
          id={id + "-" + index}
          list={id}
          value={row.name ?? ""}
          {disabled}
          placeholder={m.flow_transcript_editor_name_placeholder()}
          oninput={(e) =>
            onChange(
              withProposalSupport(
                rows.map((r) =>
                  r.label === row.label ? { ...r, name: e.currentTarget.value || null } : r
                ),
                proposed
              )
            )}
        />
        <p class="text-secondary mt-1 text-xs">
          {countMessage(
            row.lineCount,
            m.flow_transcript_editor_lines_one,
            m.flow_transcript_editor_lines
          )}{asProposed ? proposalNote(row) : ""}
        </p>
        <details
          open={whyOpen.has(row.label)}
          ontoggle={(event) =>
            event.currentTarget.open ? whyOpen.add(row.label) : whyOpen.delete(row.label)}
          class="text-secondary mt-1 text-xs"
        >
          <summary
            class="focus-visible:ring-ring flex min-h-[24px] cursor-pointer list-none items-center gap-1.5 focus-visible:ring-2 [&::-webkit-details-marker]:hidden"
            ><ChevronRight
              class="size-3.5 shrink-0 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {whyOpen.has(
                row.label
              )
                ? 'rotate-90'
                : ''}"
              aria-hidden="true"
            />{m.flow_transcript_editor_why()}</summary
          >
          {#if asProposed}<p class="mt-2 leading-relaxed">
              {row.evidence || m.flow_transcript_editor_no_evidence()}
            </p>{/if}
          {#each row.samples as sample, i (i)}<p
              class="mt-1 leading-relaxed [overflow-wrap:anywhere] italic"
            >
              “{sample}”
            </p>{/each}
          {#if !row.samples.length}<p class="mt-1">
              {m.flow_transcript_editor_no_sample()}
            </p>{/if}
        </details>
      </div>
      <Button
        variant="outline"
        size="icon-lg"
        class="mt-0.5 rounded-full"
        aria-label={m.flow_transcript_editor_listen_speaker({ number: index + 1 })}
        disabled={!onListen || !sampleAvailable(row.label)}
        onclick={() => onListen?.(row.label)}
      >
        <IconHeadphones class="size-4" aria-hidden="true" />
      </Button>
    </div>
  {/each}
  <p class="text-secondary text-xs">{m.flow_transcript_editor_unnamed_hint()}</p>
</details>
