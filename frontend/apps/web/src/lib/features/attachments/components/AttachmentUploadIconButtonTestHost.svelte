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

  type Props = {
    eneo: Eneo;
    /** Hands the manager to the test so it can act on the list. */
    onManager?: (manager: ReturnType<typeof initAttachmentManager>) => void;
  };
  const { eneo, onManager }: Props = $props();

  const manager = initAttachmentManager({ eneo: untrack(() => eneo) });
  untrack(() => onManager?.(manager));
</script>

<AttachmentUploadIconButton />
