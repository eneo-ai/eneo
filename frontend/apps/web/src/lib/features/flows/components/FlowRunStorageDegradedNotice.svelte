<script lang="ts">
  import { m } from "$lib/paraglide/messages";
</script>

<p
  class="border-warning-default/30 bg-warning-dimmer text-warning-stronger mb-5 rounded-md border px-3.5 py-2.5 text-sm"
  role="status"
  aria-live="polite"
>
  {m.recording_session_storage_degraded()}
</p>
