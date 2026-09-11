<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<!--
  Help text for the "let the assistant open attached files itself" switch.
  Shared by the assistant editor and the personal-assistant policy page so
  the two surfaces never drift in how they explain the setting.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  type Props = { id?: string };
  let { id }: Props = $props();
</script>

<div {id} class="text-secondary mt-1 space-y-1.5 text-sm">
  <p>
    <span class="text-default font-semibold">{m.attachments_open_files_on_label()}:</span>
    {m.attachments_open_files_on()}
  </p>
  <p>
    <span class="text-default font-semibold">{m.attachments_open_files_off_label()}:</span>
    {m.attachments_open_files_off()}
  </p>
  <p>
    <span class="text-default font-semibold">{m.attachments_open_files_example_label()}:</span>
    {m.attachments_open_files_example()}
  </p>
</div>
