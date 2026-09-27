<script lang="ts">
  import { IconPlay } from "@eneo/icons/play";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import AppIcon from "$lib/features/apps/components/AppIcon.svelte";
  import AppInput from "$lib/features/apps/components/AppInput.svelte";
  import { createAppRun } from "$lib/features/apps/createAppRun.svelte";
  import AttachmentDropArea from "$lib/features/attachments/components/AttachmentDropArea.svelte";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { m } from "$lib/paraglide/messages";

  const run = createAppRun((result, app) =>
    goto(resolve(`/dashboard/app/${app.id}/results/${result.id}`))
  );
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="flex h-full w-full flex-col overflow-y-auto" ondragenter={run.onDragEnter}>
  <div class="flex flex-col items-center gap-2 px-4 py-6">
    <AppIcon app={run.app} size="medium"></AppIcon>
    <h2 class="text-center text-xl font-bold">{formatEmojiTitle(run.app.name)}</h2>
    {#if run.app.description}
      <p class="text-secondary max-w-[50ch] text-center text-sm">
        {run.app.description}
      </p>
    {/if}
  </div>

  <div class="flex flex-grow flex-col gap-4 px-4 pb-4">
    <div class="flex w-full flex-col gap-4">
      <AppInput app={run.app} bind:text={run.text} compact />
    </div>

    {#snippet runButton()}
      <Button
        disabled={!run.hasData || run.isSubmitting}
        onclick={run.submit}
        class="h-auto w-full gap-2 py-3 text-lg"
      >
        <IconPlay />
        {run.isSubmitting ? m.submitting() : m.submit()}
      </Button>
    {/snippet}
    {#if run.hasData}
      {@render runButton()}
    {:else}
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <span {...props} class="block">{@render runButton()}</span>
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content>{m.input_data_required_tooltip()}</Tooltip.Content>
      </Tooltip.Root>
    {/if}
  </div>
</div>

{#if run.isDragging}
  <AttachmentDropArea
    bind:isDragging={run.isDragging}
    label={m.drop_files_here_upload({ appName: run.app.name })}
  />
{/if}
