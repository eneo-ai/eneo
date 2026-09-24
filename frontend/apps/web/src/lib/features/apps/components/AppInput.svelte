<script lang="ts">
  import type { App } from "@eneo/eneo-js";
  import InputAudioRecording from "./InputAudioRecording.svelte";
  import InputTextField from "./InputTextField.svelte";
  import InputUpload from "./InputUpload.svelte";

  type Props = {
    app: App;
    /** The text-field input; uploads and recordings go to the `AttachmentManager` from context. */
    text: string | null;
    compact?: boolean;
  };

  let { app, text = $bindable(), compact = false }: Props = $props();
</script>

{#each app.input_fields as input (input)}
  {#if input.type === "audio-recorder"}
    <InputAudioRecording description={input.description ?? undefined}></InputAudioRecording>
  {:else if input.type === "text-field"}
    <InputTextField description={input.description} bind:value={text} {compact} />
  {:else}
    <InputUpload {input} description={input.description ?? undefined} />
  {/if}
{/each}
