<!--
  Speaker identification for a flow's transcription. A transcription model
  writes the text; a speaker identification service granted to the space
  labels who says what. The space's only usable service is used without a
  choice; a picker appears only when the space has several, or when the
  flow's pick is no longer usable. Mirrors the backend resolver
  (eneo.flows.speaker_service).
-->
<script lang="ts">
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
    pickedId,
    disabled,
    onLabelsChange,
    onPick
  }: {
    services: SpeakerServiceLink[];
    labels: boolean;
    pickedId: string | null;
    disabled: boolean;
    onLabelsChange: (labels: boolean) => void;
    onPick: (serviceId: string) => void;
  } = $props();

  const usable = $derived(usableSpeakerServices(services));
  const picked = $derived(usable.find((service) => service.id === pickedId) ?? null);
  const pickLost = $derived(pickedId !== null && picked === null);
  // The service that will label speakers without the author choosing.
  const resolved = $derived(
    picked ?? (pickedId === null && usable.length === 1 ? usable[0] : null)
  );
  const offerPicker = $derived(usable.length > 1 || (pickLost && usable.length > 0));
  const noService = $derived(usable.length === 0);
</script>

<div
  class={[
    "rounded-lg border px-3 py-3 motion-safe:transition-colors motion-safe:duration-(--duration-quick)",
    noService ? "border-default bg-secondary/40" : "bg-primary",
    !noService && labels ? "border-accent-default/40" : "border-default"
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
    </div>
    <Switch
      checked={!noService && labels}
      disabled={disabled || noService}
      aria-label={m.flow_transcription_diarization()}
      onCheckedChange={onLabelsChange}
    />
  </div>

  {#if !noService && labels}
    <div class="border-default/60 mt-3 border-t pt-3">
      {#if offerPicker}
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
          <Select.Trigger id="flow-speaker-service" class="mt-1.5 min-h-10 w-full">
            {picked?.name ?? m.flow_transcription_speakers_choose()}
          </Select.Trigger>
          <Select.Content>
            {#each usable as service (service.id)}
              <Select.Item value={service.id} label={service.name}>{service.name}</Select.Item>
            {/each}
          </Select.Content>
        </Select.Root>
        {#if pickLost}
          <p class="text-warning-stronger mt-1.5 text-xs leading-relaxed" role="status">
            {m.flow_transcription_speakers_pick_unavailable()}
          </p>
        {:else if picked === null}
          <p class="text-secondary mt-1.5 text-xs leading-relaxed">
            {m.flow_transcription_speakers_choose_hint()}
          </p>
        {/if}
      {:else if resolved}
        <p class="text-secondary text-xs leading-relaxed">
          {m.flow_transcription_speakers_by({ name: resolved.name })}
        </p>
      {/if}
    </div>
  {/if}
</div>
