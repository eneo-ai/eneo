<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import EditService from "./EditService.svelte";
  import { dynamicColour } from "$lib/core/colours";
  import { m } from "$lib/paraglide/messages";

  const eneo = getEneo();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  export let data;

  let playgroundInput = "";
  let playgroundOutput = "";
  let runningService = false;
  const inputId = useId();

  async function runService() {
    runningService = true;
    try {
      const result = await eneo.services.run({ service: data.service, input: playgroundInput });
      if (typeof result === "string") {
        playgroundOutput = result;
      } else {
        playgroundOutput = JSON.stringify(result);
      }
    } catch (e) {
      console.error(e);
      playgroundOutput = JSON.stringify(e);
    }
    runningService = false;
  }
</script>

<svelte:head>
  <title
    >Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} - {data.service
      .name}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{ title: m.services(), href: `/spaces/${$currentSpace.routeId}/services` }}
      title={data.service.name}
    ></Page.Title>

    <Page.Tabbar>
      <Page.Flex>
        <Page.TabTrigger
          tab="playground"
          label={m.test_your_service({ serviceName: data.service.name })}
          >{m.playground()}</Page.TabTrigger
        >
        <Page.TabTrigger tab="edit">{m.settings()}</Page.TabTrigger>
      </Page.Flex>
    </Page.Tabbar>
  </Page.Header>

  <Page.Main>
    <Page.Tab id="playground">
      <div
        {...dynamicColour({ basedOn: data.service.id })}
        class="grid h-full grid-cols-1 gap-4 py-4 pr-4 md:grid-cols-2"
      >
        <div class="flex h-full flex-col items-end gap-4">
          <Field.Field class="h-full w-full">
            <Field.Label for={inputId}>{m.input()}</Field.Label>
            <Textarea id={inputId} bind:value={playgroundInput} rows={4} class="h-full" />
          </Field.Field>
          <Button onclick={runService}>
            {#if runningService}{m.running()}{:else}
              {m.run_this_service()}{/if}</Button
          >
        </div>
        <div class="flex flex-col items-end gap-1">
          <h3 class="self-start font-medium">{m.output()}</h3>
          <div
            class="border-dynamic-default bg-dynamic-dimmer text-dynamic-default h-full w-full overflow-y-auto border-b p-4 font-mono text-sm"
          >
            {runningService ? m.loading() : playgroundOutput}
          </div>

          <Button
            class="mt-3"
            onclick={() => {
              navigator.clipboard.writeText(playgroundOutput);
            }}>{m.copy_response()}</Button
          >
        </div>
      </div>
    </Page.Tab>
    <Page.Tab id="edit">
      <EditService service={data.service}></EditService>
    </Page.Tab>
  </Page.Main>
</Page.Root>
