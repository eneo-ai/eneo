<script lang="ts">
  import * as m from "$lib/paraglide/messages";
  import type { SpeakerMappingRow } from "../speakerMappingReview";
  import { speakerColorIndex } from "../transcriptSegments";
  let {
    rows,
    participants,
    inferred = false,
    disabled = false,
    onChange,
    onListen,
    sampleAvailable = () => false
  }: {
    rows: SpeakerMappingRow[];
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
</script>

<details class="border-default bg-primary min-w-0 rounded-xl border p-4" open>
  <summary
    class="text-primary focus-visible:ring-accent-default cursor-pointer text-sm font-medium focus-visible:ring-2"
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
        <input
          id={id + "-" + index}
          list={id}
          class="border-default bg-primary min-h-9 w-full rounded-md border px-3 text-sm"
          value={row.name ?? ""}
          {disabled}
          placeholder={m.flow_transcript_editor_name_placeholder()}
          oninput={(e) =>
            onChange(
              rows.map((r) =>
                r.label === row.label ? { ...r, name: e.currentTarget.value || null } : r
              )
            )}
        />
        <p class="text-muted mt-1 text-xs">
          {m.flow_transcript_editor_lines({ count: row.lineCount })} · {row.name
            ? m.flow_transcript_editor_confidence({
                confidence:
                  row.confidence === "high"
                    ? m.flow_transcript_editor_confidence_high()
                    : row.confidence === "medium"
                      ? m.flow_transcript_editor_confidence_medium()
                      : m.flow_transcript_editor_confidence_low()
              })
            : m.flow_transcript_editor_no_suggestion()}{inferred &&
          row.name &&
          !participants.includes(row.name)
            ? m.flow_transcript_editor_inferred_name()
            : ""}
        </p>
        <details class="text-muted mt-1 text-xs">
          <summary class="focus-visible:ring-accent-default cursor-pointer focus-visible:ring-2"
            >{m.flow_transcript_editor_why()}</summary
          >
          <p class="mt-2 leading-relaxed">
            {row.evidence || m.flow_transcript_editor_no_evidence()}
          </p>
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
      <button
        type="button"
        class="border-default focus-visible:ring-accent-default mt-0.5 flex size-9 items-center justify-center rounded-full border focus-visible:ring-2 disabled:opacity-40"
        aria-label={m.flow_transcript_editor_listen_speaker({ number: index + 1 })}
        disabled={!onListen || !sampleAvailable(row.label)}
        onclick={() => onListen?.(row.label)}
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          aria-hidden="true"><path d="M3 14v-3a9 9 0 0 1 18 0v3M3 13h4v8H3zM17 13h4v8h-4z" /></svg
        >
      </button>
    </div>
  {/each}
  <p class="text-muted text-xs">{m.flow_transcript_editor_unnamed_hint()}</p>
</details>
