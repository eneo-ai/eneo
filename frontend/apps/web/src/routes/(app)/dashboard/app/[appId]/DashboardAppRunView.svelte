<script lang="ts">
  import { IconPlay } from "@intric/icons/play";
  import { Button, Tooltip } from "@intric/ui";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { getIntric } from "$lib/core/Intric";
  import { IntricError, type App, type AppRunInput } from "@intric/intric-js";
  import AppIcon from "$lib/features/apps/components/AppIcon.svelte";
  import AttachmentDropArea from "$lib/features/attachments/components/AttachmentDropArea.svelte";
  import { getAppAttachmentRulesStore } from "$lib/features/attachments/getAttachmentRules";
  import { derived, type Readable } from "svelte/store";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import DashboardAppInput from "./DashboardAppInput.svelte";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();

  const app = derived(page, ($page) => $page.data.app) as Readable<App>;

  const { clearUploads } = initAttachmentManager({
    intric,
    options: { rules: getAppAttachmentRulesStore(app) }
  });

  const createEmptyInputs = () => {
    return { files: [], text: null };
  };

  let inputs: AppRunInput = createEmptyInputs();
  $: hasData = inputs.files.length > 0 || inputs.text;

  let isDragging = false;
  const dragDropEnabled = derived(app, ($app) => {
    return $app.input_fields.map((field) => field.type).some((type) => type.includes("upload"));
  });

  let isSubmitting = false;
  async function createRun() {
    if (inputs.files.length === 0 && !inputs.text) {
      alert(m.input_required_to_run_app());
      return;
    }

    try {
      isSubmitting = true;
      const result = await intric.apps.runs.create({
        app: $app,
        inputs: {
          files: inputs.files.map(({ id }) => {
            return { id };
          }),
          text: inputs.text
        }
      });
      inputs = createEmptyInputs();
      clearUploads();
      isSubmitting = false;
      goto(`/dashboard/app/${$app.id}/results/${result.id}`);
    } catch (err) {
      const msg = err instanceof IntricError ? err.getReadableMessage() : err;
      console.error(err);
      alert(m.error_running_app({ msg }));
      isSubmitting = false;
    }
  }
</script>

<!-- svelte-ignore a11y-no-static-element-interactions -->
<div
  class="flex h-full w-full flex-col overflow-y-auto"
  on:dragenter={(event) => {
    if ($dragDropEnabled) {
      event.preventDefault();
      isDragging = true;
    }
  }}
>
  <div class="flex flex-col items-center gap-2 px-4 py-6">
    <AppIcon app={$app} size="medium"></AppIcon>
    <h2 class="text-center text-xl font-bold">{formatEmojiTitle($app.name)}</h2>
    {#if $app.description}
      <p class="text-secondary max-w-[50ch] text-center text-sm">
        {$app.description}
      </p>
    {/if}
  </div>

  <div class="flex flex-grow flex-col gap-4 px-4 pb-4">
    <DashboardAppInput app={$app} bind:inputData={inputs}></DashboardAppInput>

    <Tooltip text={hasData ? undefined : m.input_data_required_tooltip()}>
      <Button
        disabled={!hasData || isSubmitting}
        variant="primary"
        on:click={createRun}
        class="flex w-full items-center justify-center gap-2 py-3 text-lg"
      >
        <IconPlay />
        {isSubmitting ? m.submitting() : m.submit()}
      </Button>
    </Tooltip>
  </div>
</div>

{#if isDragging}
  <AttachmentDropArea bind:isDragging label={m.drop_files_here_upload({ appName: $app.name })} />
{/if}

