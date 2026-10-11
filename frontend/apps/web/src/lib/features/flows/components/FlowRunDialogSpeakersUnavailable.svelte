<script lang="ts">
  import type { FlowRunContract } from "@eneo/eneo-js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { m } from "$lib/paraglide/messages";

  type SpeakerServiceGap = NonNullable<
    NonNullable<FlowRunContract["transcription"]>["speaker_labels"]["unavailable_reason"]
  >;

  let { gap }: { gap: SpeakerServiceGap } = $props();

  const reasons: Record<SpeakerServiceGap, () => string> = {
    no_service: m.flow_run_speakers_unavailable_no_service,
    none_usable: m.flow_run_speakers_unavailable_none_usable,
    picked_unavailable: m.flow_run_speakers_unavailable_picked_unavailable
  };
</script>

<div class="mx-4 mt-5 sm:mx-6 lg:mx-8">
  <Alert.Root class="border-warning-default/30 bg-warning-dimmer/60 text-warning-stronger">
    <Alert.Title>{m.flow_run_speakers_unavailable_title()}</Alert.Title>
    <Alert.Description class="text-warning-stronger">{reasons[gap]()}</Alert.Description>
  </Alert.Root>
</div>
