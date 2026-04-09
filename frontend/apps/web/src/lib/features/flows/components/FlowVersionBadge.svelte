<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "@eneo/ui";
  import { CheckCircle2, FileEdit } from "lucide-svelte";

  export let publishedVersion: number | null | undefined;

  let justChanged = false;
  let prevVersion = publishedVersion;
  $: if (publishedVersion !== prevVersion) {
    prevVersion = publishedVersion;
    justChanged = true;
    setTimeout(() => { justChanged = false; }, 600);
  }
</script>

{#if publishedVersion != null}
  <Badge
    variant="outline"
    class="gap-1.5 border-positive-default/25 bg-positive-dimmer/60 text-positive-stronger transition-all duration-300
      {justChanged ? 'scale-105 ring-2 ring-positive-default/40' : ''}"
  >
    <CheckCircle2 class="size-3" />
    {m.flow_version_published({ version: String(publishedVersion) })}
  </Badge>
{:else}
  <Badge
    variant="outline"
    class="gap-1.5 border-warning-default/25 bg-warning-dimmer/60 text-warning-stronger"
  >
    <FileEdit class="size-3" />
    {m.flow_version_draft()}
  </Badge>
{/if}
