<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { Button, Input } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import EditService from "./EditService.svelte";
  import { dynamicColour } from "$lib/core/colours";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();
  const {
    state: { currentSpace }
  } = getSpacesManager();

  export let data;

  let playgroundInput = "";
  let playgroundOutput = "";
  let runningService = false;

  async function runService() {
    runningService = true;
    try {
      const result = await intric.services.run({ service: data.service, input: playgroundInput });
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
        <Page.TabTrigger tab="playground" label={m.test_your_service({ serviceName: data.service.name })}
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
          <Input.TextArea bind:value={playgroundInput} label={m.input()} class="h-full w-full"
          ></Input.TextArea>
          <Button variant="primary" on:click={runService}>
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
            variant="primary"
            class="mt-3"
            on:click={() => {
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
