<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { toastError } from "$lib/core/errors";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { Intric } from "@intric/intric-js";
  import type { Writable } from "svelte/store";

  type Role = Awaited<ReturnType<Intric["helpAssistants"]["admin"]["listRoles"]>>[number];
  type Applications = Awaited<ReturnType<Intric["spaces"]["listApplications"]>>;
  // The space-applications endpoint returns each app type as a paginated
  // `{ items, count }` object, so candidates live under `.assistants.items`.
  type AssistantCandidate = NonNullable<Applications>["assistants"]["items"][number];

  let {
    role,
    intric,
    openController
  }: { role: Role; intric: Intric; openController: Writable<boolean> } = $props();

  // Candidates are the org-space's assistants minus the one already assigned.
  // Helper assistants live in the org-space; the picker lists what `assign`
  // will accept (the service requires the assistant to live there, PRD §4).
  let candidates = $state<AssistantCandidate[]>([]);
  let hasLoaded = $state(false);
  let loadFailed = $state(false);

  const loadCandidates = createAsyncState(async () => {
    loadFailed = false;
    try {
      const applications = await intric.spaces.listApplications({ id: role.org_space_id });
      const assistants: AssistantCandidate[] = applications?.assistants?.items ?? [];
      candidates = assistants.filter((assistant) => assistant.id !== role.assistant_id);
      hasLoaded = true;
    } catch (e) {
      loadFailed = true;
      toastError(e);
    }
  });

  const assign = createAsyncState(async (assistantId: string) => {
    try {
      await intric.helpAssistants.admin.assign({ kind: role.kind, assistant_id: assistantId });
      await invalidate("admin:help-assistants:load");
      $openController = false;
    } catch (e) {
      toastError(e);
    }
  });

  // Lazy-load the first time the picker opens; re-fetch on a later open after
  // a failed attempt so a transient error doesn't leave the list empty.
  $effect(() => {
    if ($openController && !loadCandidates.isLoading && (!hasLoaded || loadFailed)) {
      loadCandidates();
    }
  });
</script>

<Dialog.Root {openController}>
  <Dialog.Content>
    <Dialog.Title>{m.admin_help_assistants_reassign_dialog_title()}</Dialog.Title>

    <div class="flex flex-col gap-1 py-2">
      {#if loadCandidates.isLoading}
        <p class="text-secondary px-1 py-2">{m.loading()}</p>
      {:else if loadFailed}
        <p class="text-secondary px-1 py-2">{m.prompt_guide_error_generic()}</p>
      {:else if candidates.length === 0}
        <p class="text-secondary px-1 py-2">{m.admin_help_assistants_reassign_empty()}</p>
      {:else}
        {#each candidates as candidate (candidate.id)}
          <Button
            variant="outlined"
            disabled={assign.isLoading}
            onclick={() => assign(candidate.id)}>{candidate.name}</Button
          >
        {/each}
      {/if}
    </div>

    <Dialog.Controls>
      <Button onclick={() => ($openController = false)}>{m.cancel()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
