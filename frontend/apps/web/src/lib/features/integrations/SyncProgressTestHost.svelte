<script lang="ts">
  import { useSyncProgress } from "./useSyncProgress.svelte";

  let { active = true }: { active?: boolean } = $props();

  const tracker = useSyncProgress({ active: () => active });
</script>

<p>{Object.keys(tracker.byId).join(",")}</p>
