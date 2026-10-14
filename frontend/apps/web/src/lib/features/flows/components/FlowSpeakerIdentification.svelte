<!--
  Word timings and speakers for a flow's transcription. A transcription model
  writes the text; a service granted to the space (Vemsa) times every word, so
  a reader can click a word and hear it, and labels who says what when the
  flow asks for it. The author chooses the service first, or "none" for text
  only; identifying speakers depends on that choice. Nothing is chosen on the
  flow's behalf here (the server fills the organisation's default into a draft
  that has made no choice), and a choice the space can no longer use stays
  visible with its reason until the author changes it. A step that names the
  speakers keeps identification on. Mirrors the backend resolver
  (resolve_speaker_service in eneo.flows.transcription_config).
-->
<script lang="ts">
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import CircleQuestionMark from "@lucide/svelte/icons/circle-question-mark";
  import { m } from "$lib/paraglide/messages";
  import { usableSpeakerServices } from "$lib/features/flows/flowEditorMetadata";

  type SpeakerServiceLink = {
    id: string;
    name: string;
    meets_security_classification: boolean;
    available: boolean;
    /** The organisation's default: what a new draft gets filled in. */
    is_default: boolean;
  };

  let {
    services,
    labels,
    required,
    pickedId,
    chosenNone,
    maxSpeakers,
    disabled,
    onLabelsChange,
    onPick,
    onMaxSpeakersChange
  }: {
    services: SpeakerServiceLink[];
    labels: boolean;
    /** A step names the speakers, so every run labels them whatever the switch says. */
    required: boolean;
    pickedId: string | null;
    /** The author chose no service: text only, without word timings or speakers. */
    chosenNone: boolean;
    /** The most speakers the service may label; null lets it count them. */
    maxSpeakers: number | null;
    disabled: boolean;
    onLabelsChange: (labels: boolean) => void;
    /** A service, or null for none. */
    onPick: (serviceId: string | null) => void;
    onMaxSpeakersChange: (maxSpeakers: number | null) => void;
  } = $props();

  const NONE = "none";
  let maxSpeakersRejected = $state(false);

  // Empty means automatic. Anything but a whole number of at least 1 is
  // refused and the field shows the saved value again, so it never displays a
  // number the flow will not keep.
  function maxSpeakersEntered(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    const raw = input.value.trim();
    const value = raw === "" ? null : Number(raw);
    maxSpeakersRejected = value !== null && !(Number.isInteger(value) && value >= 1);
    if (maxSpeakersRejected) input.value = maxSpeakers === null ? "" : String(maxSpeakers);
    else onMaxSpeakersChange(value);
  }

  // The default is named, so an author sees why a new flow came with it.
  function optionLabel(service: SpeakerServiceLink): string {
    return service.is_default
      ? m.flow_transcription_speakers_default_option({ name: service.name })
      : service.name;
  }

  const usable = $derived(usableSpeakerServices(services));
  const picked = $derived(usable.find((service) => service.id === pickedId) ?? null);
  const lost = $derived(pickedId !== null && picked === null);
  // Still granted to the space when it is switched off or below the space's
  // classification, so its name and the reason can be shown.
  const lostLink = $derived(
    lost ? (services.find((service) => service.id === pickedId) ?? null) : null
  );
  const lostReason = $derived.by(() => {
    if (!lost) return null;
    if (!lostLink) return m.flow_transcription_speakers_lost_removed();
    return lostLink.meets_security_classification
      ? m.flow_transcription_speakers_lost_disabled({ name: lostLink.name })
      : m.flow_transcription_speakers_lost_classification({ name: lostLink.name });
  });
  // "None" is the way out of a lost choice, unless a step needs the speakers.
  const lostAction = $derived(
    usable.length > 0
      ? required
        ? m.flow_transcription_speakers_lost_choose_other_required
        : m.flow_transcription_speakers_lost_choose_other
      : required
        ? m.flow_transcription_speakers_lost_no_other_required
        : m.flow_transcription_speakers_lost_no_other
  );
  const on = $derived(required || (labels && !chosenNone));
  // Nothing to choose, nothing asked and nothing lost: the card only says why.
  const noService = $derived(usable.length === 0 && !required && !lost);
  const showPicker = $derived(usable.length > 0 || lost);
  // What the choice means, said once under it.
  const consequence = $derived.by(() => {
    if (lost) return null;
    if (picked)
      return on
        ? m.flow_transcription_speakers_sends_to_speakers({ name: picked.name })
        : m.flow_transcription_speakers_sends_to({ name: picked.name });
    if (chosenNone) return m.flow_transcription_speakers_none_note();
    if (required) return m.flow_transcription_speakers_choose_hint_required();
    return on
      ? m.flow_transcription_speakers_choose_hint()
      : m.flow_transcription_speakers_choose_hint_timing();
  });
  const triggerLabel = $derived(
    picked
      ? optionLabel(picked)
      : chosenNone
        ? m.flow_transcription_speakers_none_option()
        : (lostLink?.name ?? m.flow_transcription_speakers_choose())
  );
</script>

<div
  class={[
    "rounded-lg border px-3 py-3 motion-safe:transition-colors motion-safe:duration-(--duration-quick)",
    noService ? "border-default bg-secondary/40" : "bg-primary",
    picked ? "border-accent-default/40" : "border-default"
  ]}
>
  <div class="min-w-0">
    <div class="flex items-center gap-1.5">
      <p class={["text-sm font-medium", noService && "text-secondary"]}>
        {m.flow_transcription_timing_title()}
      </p>
      {#if noService}
        <Tooltip.Provider delayDuration={150}>
          <Tooltip.Root>
            <Tooltip.Trigger aria-label={m.flow_transcription_speakers_unavailable_label()}>
              <CircleQuestionMark
                class="text-secondary hover:text-primary size-3.5 transition-colors"
                aria-hidden="true"
              />
            </Tooltip.Trigger>
            <!-- To the side, so the open hint never covers the model picker above. -->
            <Tooltip.Content side="right" class="max-w-72">
              {m.flow_transcription_speakers_unavailable_help()}
            </Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      {/if}
    </div>
    <p class="text-secondary mt-1 text-xs leading-relaxed">
      {noService ? m.flow_transcription_timing_none_in_space() : m.flow_transcription_timing_desc()}
    </p>
  </div>

  {#if !noService}
    {#if showPicker}
      <div class="mt-3">
        <label class="text-sm font-medium" for="flow-speaker-service">
          {m.flow_transcription_speakers_service_label()}
        </label>
        <Select.Root
          type="single"
          value={picked?.id ?? (chosenNone ? NONE : "")}
          {disabled}
          onValueChange={(value) => {
            if (value) onPick(value === NONE ? null : value);
          }}
        >
          <Select.Trigger
            id="flow-speaker-service"
            class="mt-1.5 min-h-10 w-full"
            aria-invalid={lost || undefined}
            aria-describedby="flow-speaker-service-note"
          >
            {triggerLabel}
          </Select.Trigger>
          <Select.Content>
            {#each usable as service (service.id)}
              <Select.Item value={service.id} label={optionLabel(service)}>
                {optionLabel(service)}
              </Select.Item>
            {/each}
            <Select.Separator />
            <!-- A step that names the speakers needs a service; the note under the
                 picker says so, so the option is shown and not offered. -->
            <Select.Item
              value={NONE}
              label={m.flow_transcription_speakers_none_option()}
              disabled={required}
            >
              {m.flow_transcription_speakers_none_option()}
            </Select.Item>
          </Select.Content>
        </Select.Root>
        {#if lostReason}
          <p
            id="flow-speaker-service-note"
            class="text-warning-stronger mt-1.5 text-xs leading-relaxed"
            role="status"
          >
            {lostReason}
            {lostAction()}
          </p>
        {:else}
          <p id="flow-speaker-service-note" class="text-secondary mt-1.5 text-xs leading-relaxed">
            {consequence}
          </p>
        {/if}
      </div>
    {:else}
      <p class="text-warning-stronger mt-3 text-xs leading-relaxed" role="status">
        {m.flow_transcription_speakers_required_no_service()}
      </p>
    {/if}

    <div class="border-default/60 mt-3 border-t pt-3">
      <div class="flex items-start justify-between gap-4">
        <div class="min-w-0">
          <p class={["text-sm font-medium", chosenNone && !required && "text-secondary"]}>
            {m.flow_transcription_diarization()}
          </p>
          <!-- A switch that cannot be turned off is not told how to turn off. -->
          <p class="text-secondary mt-1 text-xs leading-relaxed">
            {required
              ? m.flow_transcription_speakers_required_note()
              : chosenNone
                ? m.flow_transcription_speakers_needs_service()
                : m.flow_transcription_diarization_desc()}
          </p>
        </div>
        <Switch
          checked={on}
          disabled={disabled || required || chosenNone}
          aria-label={m.flow_transcription_diarization()}
          onCheckedChange={onLabelsChange}
        />
      </div>

      {#if on && picked}
        <div class="mt-3 grid items-start gap-x-4 gap-y-1.5 sm:grid-cols-[10rem_1fr]">
          <div>
            <label class="text-sm font-medium" for="flow-speaker-max">
              {m.flow_transcription_speakers_max_label()}
            </label>
            <Input
              id="flow-speaker-max"
              type="number"
              inputmode="numeric"
              min="1"
              step="1"
              class="mt-1.5"
              placeholder={m.flow_transcription_speakers_max_placeholder()}
              value={maxSpeakers ?? ""}
              {disabled}
              aria-invalid={maxSpeakersRejected || undefined}
              aria-describedby={maxSpeakersRejected ? "flow-speaker-max-error" : undefined}
              onchange={maxSpeakersEntered}
            />
            {#if maxSpeakersRejected}
              <p
                id="flow-speaker-max-error"
                class="text-negative-stronger mt-1.5 text-xs leading-relaxed"
                role="alert"
              >
                {m.flow_transcription_speakers_max_invalid()}
              </p>
            {/if}
          </div>
          <p class="text-secondary text-xs leading-relaxed sm:pt-7">
            {m.flow_transcription_speakers_max_help()}
          </p>
        </div>
      {/if}
    </div>
  {/if}
</div>
