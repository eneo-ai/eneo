<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { m } from "$lib/paraglide/messages";
</script>

<Alert.Root
  class="border-warning-default/30 bg-warning-dimmer/60 text-warning-stronger mb-5"
  role="status"
>
  <Alert.Description class="text-warning-stronger/90">
    {m.recording_session_storage_degraded()}
  </Alert.Description>
</Alert.Root>
