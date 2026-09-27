<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { m } from "$lib/paraglide/messages";
  import type { JournalDegradation } from "$lib/features/audio/recordingJournal";

  let { reason = "failed" }: { reason?: JournalDegradation } = $props();
</script>

<Alert.Root
  class="border-warning-default/30 bg-warning-dimmer/60 text-warning-stronger mb-5"
  role="status"
>
  <Alert.Description class="text-warning-stronger/90">
    {reason === "failed"
      ? m.recording_session_storage_degraded()
      : m.recording_session_storage_on_part_end()}
  </Alert.Description>
</Alert.Root>
