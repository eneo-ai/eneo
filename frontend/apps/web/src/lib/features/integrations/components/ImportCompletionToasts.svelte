<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { get } from "svelte/store";
  import { goto } from "$app/navigation";
  import { toast } from "$lib/components/toast";
  import { getJobManager } from "$lib/features/jobs/JobManager";
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

  function settledHere() {
    return settledImports(get(pendingImports), get(jobs), get(jobsLoaded)).filter(
      (pending) => pending.spaceRouteId === get(currentSpace).routeId
    );
  }

  async function report() {
    const jobList = get(jobs);
    const routeId = get(currentSpace).routeId;
    const local = settledHere();
    if (local.length === 0) return;

    // A stale store would read a not-yet-listed item as deleted: wait for the next run instead.
    if (!(await refreshCurrentSpace("knowledge"))) return;
    const space = get(currentSpace);
    if (disposed || space.routeId !== routeId) return;
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

  // One active read and at most one queued report. Retry settled imports even
  // after job polling stops: a transient space read must not lose the notice.
  let queue = Promise.resolve();
  let queued = false;
  let disposed = false;
  let retry: ReturnType<typeof setTimeout> | undefined;
  let retryDelay = 2_000;

  function enqueueReport() {
    if (disposed || queued || document.hidden) return;
    clearTimeout(retry);
    queued = true;
    queue = queue.then(async () => {
      queued = false;
      if (disposed) return;
      try {
        await report();
      } catch (error) {
        console.error("Could not report the result of an import", error);
      } finally {
        if (!disposed && !queued && settledHere().length > 0) {
          retry = setTimeout(enqueueReport, retryDelay);
          retryDelay = Math.min(30_000, retryDelay * 2);
        } else {
          retryDelay = 2_000;
        }
      }
    });
  }

  onMount(() => {
    const onVisibility = () => {
      if (!document.hidden && settledHere().length > 0) enqueueReport();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      disposed = true;
      clearTimeout(retry);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  });

  const spaceId = $derived($currentSpace.id);
  $effect(() => {
    // A successful unchanged job poll also retries a previously unresolved result.
    void $jobs;
    void $pendingImports;
    void spaceId;
    if (!$jobsLoaded) return;
    untrack(() => {
      if (settledHere().length > 0) enqueueReport();
    });
  });
</script>
