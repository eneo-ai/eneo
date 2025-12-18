<script lang="ts">
  import { getAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import type { App, AppRunInput } from "@intric/intric-js";
  import InputUpload from "../../../spaces/[spaceId]/apps/[appId]/run/InputUpload.svelte";
  import DashboardInputTextField from "./DashboardInputTextField.svelte";
  import InputAudioRecording from "../../../spaces/[spaceId]/apps/[appId]/run/InputAudioRecording.svelte";

  export let app: App;
  export let inputData: AppRunInput;

  const {
    state: { attachments }
  } = getAttachmentManager();

  $: inputData.files = $attachments.map((a) => a.fileRef).filter((a) => a !== undefined);
</script>

<div class="flex w-full flex-col gap-4">
  {#each app.input_fields as input (input)}
    {#if input.type === "audio-recorder"}
      <InputAudioRecording description={input.description ?? undefined}></InputAudioRecording>
    {:else if input.type === "text-field"}
      <DashboardInputTextField
        description={input.description ?? undefined}
        bind:value={inputData.text}
      ></DashboardInputTextField>
    {:else}
      <InputUpload {input} description={input.description ?? undefined}></InputUpload>
    {/if}
  {/each}
</div>
