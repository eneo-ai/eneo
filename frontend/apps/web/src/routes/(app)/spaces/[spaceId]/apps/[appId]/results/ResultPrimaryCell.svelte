<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Button } from "@intric/ui";
  import type { App, AppRun } from "@intric/intric-js";
  import AppResultInputList from "$lib/features/apps/components/AppResultInputList.svelte";
  import { localizeHref } from "$lib/paraglide/runtime";
  export let run: Pick<AppRun, "input" | "id">;
  export let app: App;
  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

<Button unstyled href={localizeHref(`/spaces/${$currentSpace.routeId}/apps/${app.id}/results/${run.id}`)}>
  <AppResultInputList {run}></AppResultInputList>
</Button>
