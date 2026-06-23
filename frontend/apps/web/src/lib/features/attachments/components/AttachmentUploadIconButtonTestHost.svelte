<!--
    Test-only host: AttachmentUploadIconButton reads the AttachmentManager from
    context, which is keyed on a private Symbol, so tests must mount it through
    a parent that calls initAttachmentManager.
-->
<script lang="ts">
  import { untrack } from "svelte";
  import type { Intric } from "@intric/intric-js";
  import { initAttachmentManager } from "../AttachmentManager";
  import AttachmentUploadIconButton from "./AttachmentUploadIconButton.svelte";

  type Props = { intric: Intric };
  const { intric }: Props = $props();

  initAttachmentManager({ intric: untrack(() => intric) });
</script>

<AttachmentUploadIconButton />
