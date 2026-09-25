<!-- Test-only host: AttachmentDropzone reads the AttachmentManager from context. -->
<script lang="ts">
  import { untrack } from "svelte";
  import type { Eneo } from "@eneo/eneo-js";
  import { initAttachmentManager, type AttachmentRules } from "../AttachmentManager";
  import AttachmentDropzone from "./AttachmentDropzone.svelte";

  type Props = { eneo: Eneo; rules: AttachmentRules; multiple?: boolean };
  const { eneo, rules, multiple }: Props = $props();

  initAttachmentManager({ eneo: untrack(() => eneo), options: { rules: untrack(() => rules) } });
</script>

<AttachmentDropzone {multiple} />
