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
  // Mounted where the space is known, so it outlives the import dialog.

  const {
    state: { jobs }
  } = getJobManager();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  async function report() {
    const settled = settledImports(get(pendingImports), get(jobs));
    if (settled.length === 0) return;
    untrackImports(settled.map((item) => item.jobId));

    await refreshCurrentSpace("knowledge");
    const space = get(currentSpace);
    for (const pending of settled) {
      const knowledge = space.knowledge.integrationKnowledge.find(
        (item) => item.id === pending.knowledgeId && item.space_id === space.id
      );
      if (!knowledge) continue;
      const outcome = describeImportOutcome(knowledge, pending.spaceRouteId);
      if (!outcome.synced) continue;
      if (outcome.error !== null) {
        const message = m.integration_import_failed_toast({ name: outcome.name });
        toast.error(outcome.error ? `${message}: ${outcome.error}` : message);
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
  }

  $effect(() => {
    const event = $jobCompletionEvents;
    if (!event) return;
    untrack(() => void report());
  });
</script>
