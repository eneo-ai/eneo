<!--
  Speaker identification for a flow's transcription. A transcription model
  writes the text; a speaker identification service granted to the space
  labels who says what. The flow's author chooses that service: nothing is
  ever chosen on the flow's behalf, and a choice the space can no longer use
  stays visible with its reason until the author changes it. A step that
  names the speakers keeps identification on. Mirrors the backend resolver
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
  };

  let {
    services,
    labels,
    required,
    pickedId,
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
    /** The most speakers the service may label; null lets it count them. */
    maxSpeakers: number | null;
    disabled: boolean;
    onLabelsChange: (labels: boolean) => void;
    onPick: (serviceId: string) => void;
    onMaxSpeakersChange: (maxSpeakers: number | null) => void;
  } = $props();

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
  const on = $derived(labels || required);
  // Nothing to choose and nothing asked, so the card is greyed out. A flow
  // that needs the labels stays live and says what is missing; one still
  // labelling with a lost choice keeps its switch as the way out.
  const noService = $derived(usable.length === 0 && !required && !(lost && labels));
  // Switching labels off is a way out only while no step needs them.
  const lostAction = $derived(
    usable.length > 0
      ? required
        ? m.flow_transcription_speakers_lost_choose_other_required
        : m.flow_transcription_speakers_lost_choose_other
      : required
        ? m.flow_transcription_speakers_lost_no_other_required
        : m.flow_transcription_speakers_lost_no_other
  );
  const serviceNote = $derived(
    lost ? "flow-speaker-service-lost" : picked ? undefined : "flow-speaker-service-hint"
  );
</script>

<div
  class={[
    "rounded-lg border px-3 py-3 motion-safe:transition-colors motion-safe:duration-(--duration-quick)",
    noService ? "border-default bg-secondary/40" : "bg-primary",
    on && picked ? "border-accent-default/40" : "border-default"
  ]}
>
  <div class="flex items-start justify-between gap-4">
    <div class="min-w-0">
      <div class="flex items-center gap-1.5">
        <p class={["text-sm font-medium", noService && "text-secondary"]}>
          {m.flow_transcription_diarization()}
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
        {m.flow_transcription_diarization_desc()}
      </p>
      {#if required && !noService}
        <p class="text-secondary mt-1 text-xs leading-relaxed">
          {m.flow_transcription_speakers_required_note()}
        </p>
      {/if}
    </div>
    <Switch
      checked={!noService && on}
      disabled={disabled || noService || required}
      aria-label={m.flow_transcription_diarization()}
      onCheckedChange={onLabelsChange}
    />
  </div>

  {#if !noService && on}
    <div class="border-default/60 mt-3 space-y-3 border-t pt-3">
      <div>
        {#if usable.length > 0}
          <label class="text-sm font-medium" for="flow-speaker-service">
            {m.flow_transcription_speakers_service_label()}
          </label>
          <Select.Root
            type="single"
            value={picked?.id ?? ""}
            {disabled}
            onValueChange={(value) => {
              if (value) onPick(value);
            }}
          >
            <Select.Trigger
              id="flow-speaker-service"
              class="mt-1.5 min-h-10 w-full"
              aria-invalid={lost || undefined}
              aria-describedby={serviceNote}
            >
              {picked?.name ?? lostLink?.name ?? m.flow_transcription_speakers_choose()}
            </Select.Trigger>
            <Select.Content>
              {#each usable as service (service.id)}
                <Select.Item value={service.id} label={service.name}>{service.name}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        {/if}
        {#if lostReason}
          <p
            id="flow-speaker-service-lost"
            class={["text-warning-stronger text-xs leading-relaxed", usable.length > 0 && "mt-1.5"]}
            role="status"
          >
            {lostReason}
            {lostAction()}
          </p>
        {:else if usable.length === 0}
          <p class="text-warning-stronger text-xs leading-relaxed" role="status">
            {m.flow_transcription_speakers_required_no_service()}
          </p>
        {:else if !picked}
          <p id="flow-speaker-service-hint" class="text-secondary mt-1.5 text-xs leading-relaxed">
            {required
              ? m.flow_transcription_speakers_choose_hint_required()
              : m.flow_transcription_speakers_choose_hint()}
          </p>
        {/if}
      </div>
      {#if picked}
        <div class="grid items-start gap-x-4 gap-y-1.5 sm:grid-cols-[10rem_1fr]">
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
