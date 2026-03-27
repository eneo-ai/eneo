<script lang="ts">
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import type { App, AppRunInput } from "@eneo/eneo-js";
  import InputUpload from "./InputUpload.svelte";
  import InputTextField from "./InputTextField.svelte";
  import InputAudioRecording from "./InputAudioRecording.svelte";

  export let app: App;
  export let inputData: AppRunInput;

  const {
    state: { attachments }
  } = getAttachmentManager();

  $: inputData.files = $attachments.map((a) => a.fileRef).filter((a) => a !== undefined);
</script>

{#each app.input_fields as input (input)}
  {#if input.type === "audio-recorder"}
    <InputAudioRecording description={input.description ?? undefined}></InputAudioRecording>
  {:else if input.type === "text-field"}
    <InputTextField description={input.description ?? undefined} bind:value={inputData.text}
    ></InputTextField>
  {:else}
    <InputUpload {input} description={input.description ?? undefined}></InputUpload>
  {/if}
{/each}
