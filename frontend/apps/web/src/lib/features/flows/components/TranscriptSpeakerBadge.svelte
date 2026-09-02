<script module lang="ts">
  export type SpeakerOption = { label: string; display: string; colorClass: string };
</script>

<script lang="ts">
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { m } from "$lib/paraglide/messages";

  let {
    display,
    colorClass,
    editable = false,
    overridden = false,
    changedFrom = null,
    menuLabel = "",
    options = [],
    newSpeakerLabel = "",
    disabled = false,
    onSelect,
    onReset
  }: {
    /** Name (or raw label) shown in the badge. */
    display: string;
    colorClass: string;
    /** Renders the badge as a speaker menu instead of a plain chip. */
    editable?: boolean;
    /** True when a speaker edit put this badge here (offers a reset). */
    overridden?: boolean;
    /** Display name of the original speaker, for the overridden tooltip. */
    changedFrom?: string | null;
    menuLabel?: string;
    options?: SpeakerOption[];
    /** The minted label behind "Ny talare". */
    newSpeakerLabel?: string;
    disabled?: boolean;
    onSelect?: (label: string) => void;
    onReset?: () => void;
  } = $props();

  const badgeClass =
    "mr-1.5 inline-block rounded px-1.5 py-px align-baseline text-xs font-semibold";
  const overriddenClass = $derived(overridden ? "ring-accent-default/60 ring-1 ring-inset" : "");
  const title = $derived(
    overridden && changedFrom
      ? m.flow_run_transcript_speaker_changed_from({ original: changedFrom })
      : undefined
  );
</script>

{#if editable}
  <DropdownMenu.DropdownMenu>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <button
          {...props}
          type="button"
          {disabled}
          aria-label={menuLabel}
          {title}
          class="{badgeClass} {colorClass} {overriddenClass} cursor-pointer transition-shadow hover:ring-1 hover:ring-current/40 disabled:cursor-default"
        >
          {display}
        </button>
      {/snippet}
    </DropdownMenu.Trigger>
    <DropdownMenu.Content align="start" class="min-w-40">
      <DropdownMenu.Label class="text-xs">
        {m.flow_run_transcript_change_speaker()}
      </DropdownMenu.Label>
      {#each options as option (option.label)}
        <DropdownMenu.Item onclick={() => onSelect?.(option.label)}>
          <span class="inline-block rounded px-1.5 py-px text-xs font-semibold {option.colorClass}">
            {option.display}
          </span>
        </DropdownMenu.Item>
      {/each}
      <DropdownMenu.Separator />
      <DropdownMenu.Item onclick={() => onSelect?.(newSpeakerLabel)}>
        {m.flow_run_transcript_new_speaker()}
        <span class="text-muted ml-1 text-xs">({newSpeakerLabel})</span>
      </DropdownMenu.Item>
      {#if overridden && onReset}
        <DropdownMenu.Separator />
        <DropdownMenu.Item onclick={() => onReset?.()}>
          {m.flow_run_transcript_reset_speaker()}
        </DropdownMenu.Item>
      {/if}
    </DropdownMenu.Content>
  </DropdownMenu.DropdownMenu>
{:else}
  <span class="{badgeClass} {colorClass} {overriddenClass}" {title}>{display}</span>
{/if}
