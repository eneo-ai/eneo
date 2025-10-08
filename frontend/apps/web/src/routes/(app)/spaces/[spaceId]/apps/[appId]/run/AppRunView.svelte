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
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import AppInput from "./AppInput.svelte";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  // Small hack to get the selected app as a store, if exported as prop we would need to
  // manually transform it to a store and update it everytime the exported prop is updated.
  // Why do we need it as a store in the first place? So we don't have to recreate the
  // `AttachmentManager` with new rules everytime we change the selected app. This is mostly
  // relevant when
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
      // Reset the app, should not really be needed when we redirect to the result bc the component will unmount
      inputs = createEmptyInputs();
      clearUploads();
      isSubmitting = false;
      // Forward to the newly created run
      goto(`/spaces/${$currentSpace.routeId}/apps/${$app.id}/results/${result.id}`);
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
  class="relative flex h-full w-full flex-grow flex-col items-center justify-center gap-2 p-4 pl-0"
  on:dragenter={(event) => {
    if ($dragDropEnabled) {
      event.preventDefault();
      isDragging = true;
    }
  }}
>
  <div
    class="border-default bg-primary flex w-full max-w-[64ch] flex-col gap-2 rounded-xl border p-2 shadow-xl"
  >
    <div class="-mt-[2.5rem] flex flex-grow flex-col items-center justify-center rounded pb-2">
      <div class="bg-primary flex items-center gap-4 rounded-2xl pr-6 pl-4">
        <AppIcon app={$app} size="medium"></AppIcon>
        <span class="text-4xl font-extrabold">{formatEmojiTitle($app.name)}</span>
      </div>
    </div>

    {#if $app.description}
      <p class="text-secondary mx-auto max-w-[50ch] pb-2 text-center">
        {$app.description}
      </p>
    {/if}
    <div
      class="border-dynamic-dimmer bg-dynamic-dimmer flex min-h-[14rem] w-full flex-grow flex-col items-center justify-center gap-4 rounded-lg border py-6"
    >
      <AppInput app={$app} bind:inputData={inputs}></AppInput>
    </div>

    <Tooltip text={hasData ? undefined : m.input_data_required_tooltip()}>
      <Button
        disabled={!hasData || isSubmitting}
        unstyled
        on:click={createRun}
        class="border-stronger bg-dynamic-default text-on-fill hover:border-dynamic-default hover:bg-dynamic-dimmer hover:text-dynamic-stronger flex w-full cursor-pointer items-center justify-center gap-2 rounded-md border px-4 py-2 pl-3 text-lg shadow-lg "
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
