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
    state: { jobs }
  } = getJobManager();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  function reportFailure(name: string, error: string | null) {
    const message = m.integration_import_failed_toast({ name });
    toast.error(error ? `${message}: ${error}` : message);
  }

  async function report() {
    const jobList = get(jobs);
    const settled = settledImports(get(pendingImports), jobList);
    if (settled.length === 0) return;

    await refreshCurrentSpace("knowledge");
    const space = get(currentSpace);
    const reported: string[] = [];
    for (const pending of settled) {
      const knowledge = space.knowledge.integrationKnowledge.find(
        (item) => item.id === pending.knowledgeId && item.space_id === space.id
      );
      if (!knowledge) continue;
      const outcome = describeImportOutcome(knowledge, pending.spaceRouteId);
      if (!outcome.synced) {
        // The job failed before the sync wrote any status; nothing more will come.
        const job = jobList.find((candidate) => candidate.id === pending.jobId);
        if (job?.status !== "failed") continue;
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
  // not both read the same pending list and report an import twice.
  let queue = Promise.resolve();
  function enqueueReport() {
    queue = queue.then(report, report);
  }

  $effect(() => {
    const event = $jobCompletionEvents;
    if (!event) return;
    untrack(enqueueReport);
  });

  $effect(() => {
    void $currentSpace.id;
    untrack(() => {
      if (get(pendingImports).length > 0) enqueueReport();
    });
  });
</script>
