<script lang="ts">
  import { untrack } from "svelte";
  import { get } from "svelte/store";
  import { goto } from "$app/navigation";
  import { toast } from "$lib/components/toast";
  import { getJobManager, jobCompletionEvents } from "$lib/features/jobs/JobManager";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import {
    describeImportOutcome,
    pendingImports,
    settledImports,
    untrackImports
  } from "../importCompletion";

  // Reports the result of each queued import once its first sync job settles.
  // Mounted where the space is known, so it outlives the import dialog. An
  // import whose item is not in the current space stays pending until the
  // person is back in that space.

  const {
    state: { jobs, jobsLoaded }
  } = getJobManager();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  // Long enough to reach the toast's action; the close button ends it sooner.
  const RESULT_TOAST_DURATION_MS = 15_000;

  function reportFailure(name: string, error: string | null) {
    const message = m.integration_import_failed_toast({ name });
    toast.error(error ? `${message}: ${error}` : message, { duration: RESULT_TOAST_DURATION_MS });
  }

  async function report() {
    const jobList = get(jobs);
    const settled = settledImports(get(pendingImports), jobList, get(jobsLoaded));
    // Only the current space's items can be looked up; the rest wait for a return.
    const local = settled.filter((pending) => pending.spaceRouteId === get(currentSpace).routeId);
    if (local.length === 0) return;

    // A stale store would read a not-yet-listed item as deleted: wait for the next run instead.
    if (!(await refreshCurrentSpace("knowledge"))) return;
    const space = get(currentSpace);
    const reported: string[] = [];
    for (const pending of local) {
      const knowledge = space.knowledge.integrationKnowledge.find(
        (item) => item.id === pending.knowledgeId && item.space_id === space.id
      );
      if (!knowledge) {
        // Deleted before its first sync was reported: nothing left to tell.
        reported.push(pending.jobId);
        continue;
      }
      const outcome = describeImportOutcome(knowledge, pending.spaceRouteId);
      if (!outcome.synced) {
        const job = jobList.find((candidate) => candidate.id === pending.jobId);
        // A job that ended without the sync writing a status failed before it
        // got that far; one still listed as complete may yet have one written.
        if (job?.status === "complete") continue;
        reportFailure(outcome.name, null);
        reported.push(pending.jobId);
        continue;
      }
      reported.push(pending.jobId);
      if (outcome.error !== null) {
        reportFailure(outcome.name, outcome.error);
        continue;
      }
      toast.success(
        m.integration_import_result_toast({
          name: outcome.name,
          indexed: outcome.indexed,
          skipped: outcome.skipped
        }),
        {
          duration: RESULT_TOAST_DURATION_MS,
          action: {
            label: m.show(),
            // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic space route
            onClick: () => void goto(outcome.href)
          }
        }
      );
    }
    untrackImports(reported);
  }

  // Runs are serialised: a space change and a job event close together must
  // not both read the same pending list and report an import twice. A failed
  // run is logged so the chain never rejects.
  let queue = Promise.resolve();
  function enqueueReport() {
    queue = queue.then(async () => {
      try {
        await report();
      } catch (error) {
        console.error("Could not report the result of an import", error);
      }
    });
  }

  $effect(() => {
    const event = $jobCompletionEvents;
    if (!event) return;
    untrack(enqueueReport);
  });

  // Imports persisted from an earlier page load are judged by the first job
  // list, which arrives without a completion event.
  $effect(() => {
    if (!$jobsLoaded) return;
    untrack(() => {
      if (get(pendingImports).length > 0) enqueueReport();
    });
  });

  // A report refreshes the space, which publishes a new space object with
  // the same id; only a change of space may queue another report.
  const spaceId = $derived($currentSpace.id);
  $effect(() => {
    void spaceId;
    untrack(() => {
      if (get(pendingImports).length > 0) enqueueReport();
    });
  });
</script>
