<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import CheckCircle2 from "lucide-svelte/icons/check-circle-2";
  import FileEdit from "lucide-svelte/icons/file-edit";
  import { untrack } from "svelte";

  let {
    publishedVersion
  }: {
    publishedVersion: number | null | undefined;
  } = $props();

  let justChanged = $state(false);
  let prevVersion = $state(untrack(() => publishedVersion));

  $effect(() => {
    if (publishedVersion !== prevVersion) {
      prevVersion = publishedVersion;
      justChanged = true;
      const timer = setTimeout(() => {
        justChanged = false;
      }, 600);
      return () => clearTimeout(timer);
    }
  });
</script>

{#if publishedVersion != null}
  <Badge
    variant="outline"
    class="border-positive-default/25 bg-positive-dimmer/60 text-positive-stronger gap-1.5 transition-all duration-300
      {justChanged ? 'ring-positive-default/40 scale-105 ring-2' : ''}"
  >
    <CheckCircle2 class="size-3" />
    {m.flow_version_published({ version: String(publishedVersion) })}
  </Badge>
{:else}
  <Badge
    variant="outline"
    class="border-warning-default/25 bg-warning-dimmer/60 text-warning-stronger gap-1.5"
  >
    <FileEdit class="size-3" />
    {m.flow_version_draft()}
  </Badge>
{/if}
