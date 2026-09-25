<script lang="ts">
  import { IconPlay } from "@eneo/icons/play";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import AppIcon from "$lib/features/apps/components/AppIcon.svelte";
  import AppInput from "$lib/features/apps/components/AppInput.svelte";
  import { createAppRun } from "$lib/features/apps/createAppRun.svelte";
  import AttachmentDropArea from "$lib/features/attachments/components/AttachmentDropArea.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const run = createAppRun((result, app) =>
    goto(resolve(`/spaces/${$currentSpace.routeId}/apps/${app.id}/results/${result.id}`))
  );
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="relative flex h-full w-full flex-grow flex-col items-center justify-center gap-2 p-4"
  ondragenter={run.onDragEnter}
>
  <div
    class="border-default bg-primary flex w-full max-w-[64ch] flex-col gap-2 rounded-xl border p-2 shadow-xl"
  >
    <div class="-mt-[2.5rem] flex flex-grow flex-col items-center justify-center rounded pb-2">
      <div class="bg-primary flex items-center gap-4 rounded-2xl pr-6 pl-4">
        <AppIcon app={run.app} size="medium"></AppIcon>
        <span class="text-2xl font-extrabold md:text-4xl">{formatEmojiTitle(run.app.name)}</span>
      </div>
    </div>

    {#if run.app.description}
      <p class="text-secondary mx-auto max-w-[50ch] pb-2 text-center">
        {run.app.description}
      </p>
    {/if}

    {#if run.app.completion_model !== null}
      <div
        class="border-dynamic-dimmer bg-dynamic-dimmer flex min-h-[14rem] w-full flex-grow flex-col items-center justify-center gap-4 rounded-lg border py-6"
      >
        <AppInput app={run.app} bind:text={run.text} />
      </div>

      {#snippet runButton()}
        <button
          type="button"
          disabled={!run.hasData || run.isSubmitting}
          onclick={run.submit}
          class="border-stronger bg-dynamic-default text-on-fill hover:border-dynamic-default hover:bg-dynamic-dimmer hover:text-dynamic-stronger flex w-full cursor-pointer items-center justify-center gap-2 rounded-md border px-4 py-2 pl-3 text-lg shadow-lg"
        >
          <IconPlay />
          {run.isSubmitting ? m.submitting() : m.submit()}
        </button>
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
    {:else}
      <div
        class="border-dynamic-dimmer bg-dynamic-dimmer flex min-h-[14rem] w-full flex-grow flex-col items-center justify-center gap-4 rounded-lg border py-6 opacity-50"
      >
        <p class="text-secondary max-w-[50ch] text-center text-sm">
          {m.no_completion_model_description()}
        </p>
      </div>

      <button
        type="button"
        disabled
        class="border-stronger bg-dynamic-default text-on-fill flex w-full cursor-not-allowed items-center justify-center gap-2 rounded-md border px-4 py-2 pl-3 text-lg opacity-50 shadow-lg"
      >
        <IconPlay />
        {m.submit()}
      </button>
    {/if}
  </div>
</div>

{#if run.isDragging}
  <AttachmentDropArea
    bind:isDragging={run.isDragging}
    label={m.drop_files_here_upload({ appName: run.app.name })}
  />
{/if}
