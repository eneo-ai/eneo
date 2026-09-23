<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import type { App, AppRun } from "@eneo/eneo-js";
  import AppResultInputList from "$lib/features/apps/components/AppResultInputList.svelte";
  import { localizeHref } from "$lib/paraglide/runtime";
  export let run: Pick<AppRun, "input" | "id">;
  export let app: App;
  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- localizeHref handles routing -->
<a href={localizeHref(`/spaces/${$currentSpace.routeId}/apps/${app.id}/results/${run.id}`)}>
  <AppResultInputList {run}></AppResultInputList>
</a>
