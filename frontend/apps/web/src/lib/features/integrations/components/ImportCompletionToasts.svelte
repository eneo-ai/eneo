<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type { IntegrationKnowledge, Job } from "@eneo/eneo-js";
  import { get } from "svelte/store";
  import { goto } from "$app/navigation";
  import { toast } from "$lib/components/toast";
  import { getJobManager } from "$lib/features/jobs/JobManager";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import {
    describeImportOutcome,
    pendingImports,
    reportableImports,
    settledImports,
    untrackImports,
    type ImportOutcome,
    type PendingImport
  } from "../importCompletion";
  import { sourceHref } from "../sources";
  import { isCredentialsError } from "../sourceProblems";

  // Reports the result of each queued import once its first sync job settles; an
  // import of several folders gets one notice once all of them have.
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

  // The organisation's sign-in has a translated explanation; other sync errors have no code yet.
  function errorText(error: string | null): string | null {
    if (!error) return null;
    return isCredentialsError(error) ? m.integration_source_stopped_sign_in_description() : error;
  }

  function reportFailure(name: string, error: string | null) {
    const message = m.integration_import_failed_toast({ name });
    const detail = errorText(error);
    toast.error(detail ? `${message}: ${detail}` : message, { duration: RESULT_TOAST_DURATION_MS });
  }

  function showAction(href: string) {
    return {
      label: m.show(),
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic space route
      onClick: () => void goto(href)
    };
  }

  type Result = { outcome: ImportOutcome; failed: boolean; wrapperId: string | null };

  function reportOne({ outcome, failed }: Result) {
    if (failed) {
      reportFailure(outcome.name, outcome.error);
      return;
    }
    toast.success(
      m.integration_import_result_toast({
        name: outcome.name,
        indexed: outcome.indexed,
        skipped: outcome.skipped
      }),
      { duration: RESULT_TOAST_DURATION_MS, action: showAction(outcome.href) }
    );
  }

  function reportBatch(name: string, results: Result[], routeId: string) {
    const wrapperId = results.find((result) => result.wrapperId)?.wrapperId ?? null;
    const failed = results.filter((result) => result.failed);
    const href = (tab?: "problems") =>
      wrapperId
        ? sourceHref(routeId, { kind: "wrapper", id: wrapperId }, { tab })
        : `/spaces/${routeId}/knowledge?tab=integrations`;
    if (failed.length > 0) {
      const message = m.integration_import_batch_failed_toast({
        name,
        failed: failed.length,
        count: results.length
      });
      const details = new Set(failed.map((result) => errorText(result.outcome.error)));
      const [detail] = details;
      toast.error(details.size === 1 && detail ? `${message}: ${detail}` : message, {
        duration: RESULT_TOAST_DURATION_MS,
        action: showAction(href("problems"))
      });
      return;
    }
    toast.success(
      m.integration_import_batch_result_toast({
        name,
        count: results.length,
        indexed: results.reduce((sum, result) => sum + result.outcome.indexed, 0),
        skipped: results.reduce((sum, result) => sum + result.outcome.skipped, 0)
      }),
      { duration: RESULT_TOAST_DURATION_MS, action: showAction(href()) }
    );
  }

  /** The group's outcomes, without deleted items; null while one may still get its status. */
  function resultsOf(
    group: PendingImport[],
    space: { id: string; knowledge: { integrationKnowledge: IntegrationKnowledge[] } },
    jobList: Pick<Job, "id" | "status">[]
  ): Result[] | null {
    const results: Result[] = [];
    for (const pending of group) {
      const knowledge = space.knowledge.integrationKnowledge.find(
        (item) => item.id === pending.knowledgeId && item.space_id === space.id
      );
      // Deleted before its first sync was reported: nothing left to tell.
      if (!knowledge) continue;
      const outcome = describeImportOutcome(knowledge, pending.spaceRouteId);
      if (!outcome.synced) {
        const job = jobList.find((candidate) => candidate.id === pending.jobId);
        // A job that ended without the sync writing a status failed before it
        // got that far; one still listed as complete may yet have one written.
        if (job?.status === "complete") return null;
      }
      results.push({
        outcome,
        failed: !outcome.synced || outcome.error !== null,
        wrapperId: knowledge.wrapper_id ?? null
      });
    }
    return results;
  }

  function settledHere() {
    return settledImports(get(pendingImports), get(jobs), get(jobsLoaded)).filter(
      (pending) => pending.spaceRouteId === get(currentSpace).routeId
    );
  }

  async function report() {
    const jobList = get(jobs);
    const routeId = get(currentSpace).routeId;
    const groups = reportableImports(get(pendingImports), settledHere());
    if (groups.length === 0) return;

    // A stale store would read a not-yet-listed item as deleted: wait for the next run instead.
    if (!(await refreshCurrentSpace("knowledge"))) return;
    const space = get(currentSpace);
    if (disposed || space.routeId !== routeId) return;
    const reported: string[] = [];
    for (const group of groups) {
      const results = resultsOf(group, space, jobList);
      if (results === null) continue;
      reported.push(...group.map((pending) => pending.jobId));
      if (results.length === 0) continue;
      if (group.length === 1) reportOne(results[0]);
      else reportBatch(group[0].batchName ?? results[0].outcome.name, results, routeId);
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
