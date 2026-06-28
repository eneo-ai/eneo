<!--
    Test-only host: AttachmentUploadIconButton reads the AttachmentManager from
    context, which is keyed on a private Symbol, so tests must mount it through
    a parent that calls initAttachmentManager.
-->
<script lang="ts">
  import { untrack } from "svelte";
  import type { Eneo } from "@eneo/eneo-js";
  import { initAttachmentManager } from "../AttachmentManager";
  import AttachmentUploadIconButton from "./AttachmentUploadIconButton.svelte";

  type Props = { eneo: Eneo };
  const { eneo }: Props = $props();

  initAttachmentManager({ eneo: untrack(() => eneo) });
</script>

<AttachmentUploadIconButton />
