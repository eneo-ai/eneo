<!-- Test-only host: InputUpload reads the AttachmentManager from context. -->
<script lang="ts">
  import { untrack } from "svelte";
  import type { App, Eneo } from "@eneo/eneo-js";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import InputUpload from "./InputUpload.svelte";

  type Props = { eneo: Eneo; input: App["input_fields"][number] };
  const { eneo, input }: Props = $props();

  initAttachmentManager({ eneo: untrack(() => eneo) });
</script>

<InputUpload {input} />
