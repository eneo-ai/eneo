<script lang="ts">
  import { onMount } from "svelte";
  import { derived } from "svelte/store";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { pendingSyncs, settledSyncs, untrackSyncs } from "../pendingSyncs";

  // Forgets a queued sync once its job is over, so an item whose sync ended
  // without ever reporting progress does not stay queued. Mounted where the
  // jobs are polled, so it outlives the page the sync was started from.

  const {
    state: { jobs, jobsLoaded }
  } = getJobManager();

  onMount(() =>
    derived([pendingSyncs, jobs, jobsLoaded], ([$pending, $jobs, $loaded]) =>
      settledSyncs($pending, $jobs, $loaded)
    ).subscribe((settled) => untrackSyncs(settled.map((item) => item.jobId)))
  );
</script>
