<script lang="ts">
  import {
    type AssistantFleetAdvancePublic,
    EneoError,
    type OrganizationSkillPublic,
    type SkillAdoptionProjectionPagePublic,
    type SkillExecutionBlockState,
    type SkillRevisionRestorePublic
  } from "@eneo/eneo-js";
  import { beforeNavigate, invalidate } from "$app/navigation";
  import { Page } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import SkillForm from "$lib/features/skills/SkillForm.svelte";
  import SkillRevisionHistory from "$lib/features/skills/SkillRevisionHistory.svelte";
  import SkillPreview from "$lib/features/skills/SkillPreview.svelte";
  import { publishedSkillPreview } from "$lib/features/skills/skillBindingCatalog";
  import type { SkillRevisionFormValue } from "$lib/features/skills/skillBindings";
  import { getErrorMessage, SKILL_EXECUTION_BLOCK_CONFLICT } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import SkillAdoptionProjection, {
    type SkillAdoptionRun
  } from "$lib/features/skills/SkillAdoptionProjection.svelte";
  import { Info, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-svelte";
  import { onDestroy, tick, untrack } from "svelte";

  type PublicationAction = "publish" | "unpublish";
  type ExecutionAction = "block" | "unblock";
  type ReviewedAdoption =
    { status: "loaded"; page: SkillAdoptionProjectionPagePublic } | { status: "unavailable" };
  type RolloutState = SkillAdoptionRun & {
    generation: number;
    skillId: string;
    publishedRevisionId: string;
    previousPublishedRevisionId: string | null;
    stopRequested: boolean;
  };

  let { data } = $props();

  let formDirty = $state(false);
  let publicationAction = $state<PublicationAction | null>(null);
  let publicationSaving = $state(false);
  let publicationError = $state<string | null>(null);
  let updateBindingsOnPublish = $state(true);
  let rollout = $state<RolloutState | null>(null);
  let rolloutGeneration = 0;
  let componentActive = true;
  let executionBlockOverride = $state<SkillExecutionBlockState | null>(null);
  let executionBlockOverrideBase = $state<SkillExecutionBlockState | null>(null);
  let executionAction = $state<ExecutionAction | null>(null);
  let executionReason = $state("");
  let executionSaving = $state(false);
  let executionError = $state<string | null>(null);
  let refreshWarning = $state(false);
  let restoreAnnouncement = $state("");
  let advancePinned = $state<{
    skillId: string;
    revisionId: string;
    revisionNumber: number;
    publishedRevisionId: string;
  } | null>(null);
  let advanceSaving = $state(false);
  let advanceError = $state<string | null>(null);
  let advanceAnnouncement = $state("");

  const pageTitle = $derived(data.skill.display_name);
  const approvedPreview = $derived(
    data.published === null ? null : publishedSkillPreview(data.published)
  );
  const executionBlock = $derived(executionBlockOverride ?? data.executionBlock);
  const normalizedExecutionReason = $derived(executionReason.trim());
  const rolloutMutationInFlight = $derived(
    rollout?.status === "running" || rollout?.personalChat === "pending"
  );

  $effect(() => {
    if (
      executionBlockOverride !== null &&
      executionBlockOverrideBase !== null &&
      data.executionBlock !== executionBlockOverrideBase
    ) {
      executionBlockOverride = null;
      executionBlockOverrideBase = null;
    }
  });

  function publicationLabel(skill: OrganizationSkillPublic): string {
    switch (skill.publication_state) {
      case "draft":
        return m.organization_skills_status_draft();
      case "published":
        return m.organization_skills_status_published();
      case "update_pending":
        return m.organization_skills_status_update_pending();
      case "unpublished":
        return m.organization_skills_status_unpublished();
    }
  }

  function publicationVariant(skill: OrganizationSkillPublic): "default" | "secondary" | "outline" {
    if (skill.publication_state === "published") return "secondary";
    if (skill.publication_state === "update_pending") return "default";
    return "outline";
  }

  onDestroy(() => {
    componentActive = false;
    rolloutGeneration += 1;
  });

  function isCurrentSkill(skillId: string): boolean {
    return componentActive && data.skill.id === skillId;
  }

  async function refreshOrganizationSkills(skillId = data.skill.id) {
    try {
      await invalidate("organization:skills");
      if (!isCurrentSkill(skillId)) return;
      refreshWarning = false;
    } catch {
      if (!isCurrentSkill(skillId)) return;
      refreshWarning = true;
    }
  }

  async function createRevision(value: SkillRevisionFormValue) {
    const skill = data.skill;
    await data.eneo.skills.organization.createRevision({
      skillId: skill.id,
      ...value
    });
    await refreshOrganizationSkills();
  }

  async function loadMoreRevisions(cursor: string) {
    const skill = data.skill;
    return data.eneo.skills.organization.listRevisionSummaries({
      skillId: skill.id,
      cursor
    });
  }

  async function getRevision(revisionId: string) {
    const skill = data.skill;
    return data.eneo.skills.organization.getRevision({
      skillId: skill.id,
      revisionId
    });
  }

  async function restoreRevision(sourceRevisionId: string, reviewedCurrentRevisionId: string) {
    const skill = data.skill;
    return data.eneo.skills.organization.restoreRevision({
      skillId: skill.id,
      sourceRevisionId,
      reviewed_current_revision_id: reviewedCurrentRevisionId
    });
  }

  async function loadCurrentRevision() {
    const skill = await data.eneo.skills.organization.get({ skillId: data.skill.id });
    return skill.current_revision;
  }

  async function getOrganizationSkillAdoption(
    skillId: string,
    options: { limit: number; cursor: string | null }
  ): Promise<SkillAdoptionProjectionPagePublic> {
    return data.eneo.skills.organization.getAdoption({
      skillId,
      limit: options.limit,
      cursor: options.cursor
    });
  }

  async function refreshAfterRestore(outcome: SkillRevisionRestorePublic) {
    if (!outcome.created) return;
    formDirty = false;
    await refreshOrganizationSkills();
  }

  async function announceRestore(message: string) {
    restoreAnnouncement = "";
    await tick();
    restoreAnnouncement = message;
  }

  function setPublicationDialogOpen(open: boolean) {
    if (open || publicationSaving) return;
    publicationAction = null;
    publicationError = null;
  }

  function openPublicationDialog(action: PublicationAction) {
    publicationAction = action;
    publicationError = null;
    if (action === "publish") {
      updateBindingsOnPublish = true;
    }
  }

  function isCurrentRollout(run: RolloutState): boolean {
    if (!componentActive) return false;
    const currentPublishedRevisionId = data.published?.revision_id ?? null;
    return (
      data.skill.id === run.skillId &&
      (currentPublishedRevisionId === run.publishedRevisionId ||
        currentPublishedRevisionId === run.previousPublishedRevisionId) &&
      rollout?.generation === run.generation &&
      rollout.publishedRevisionId === run.publishedRevisionId
    );
  }

  function updateCurrentRollout(run: RolloutState, update: Partial<RolloutState>) {
    if (!isCurrentRollout(run) || rollout === null) return;
    rollout = { ...rollout, ...update };
  }

  function addAssistantChunk(run: RolloutState, chunk: AssistantFleetAdvancePublic) {
    if (!isCurrentRollout(run) || rollout === null) return;
    const activationUnavailable = chunk.outcomes.filter(
      (outcome) => outcome.outcome === "incompatible" && outcome.reason === "activation_unavailable"
    ).length;
    const contextWindow = chunk.outcomes.filter(
      (outcome) => outcome.outcome === "incompatible" && outcome.reason === "context_window"
    ).length;
    rollout = {
      ...rollout,
      advanced: rollout.advanced + chunk.counts.advanced,
      concurrentChange: rollout.concurrentChange + chunk.counts.concurrent_change,
      activationUnavailable: rollout.activationUnavailable + activationUnavailable,
      contextWindow: rollout.contextWindow + contextWindow
    };
  }

  async function advanceReviewedPersonalChat(run: RolloutState, pinnedRevisionId: string | null) {
    if (pinnedRevisionId === null) return;
    try {
      await data.eneo.skills.organization.advancePersonalChat({
        skillId: run.skillId,
        expected_pinned_revision_id: pinnedRevisionId,
        expected_published_revision_id: run.publishedRevisionId
      });
      updateCurrentRollout(run, { personalChat: "advanced" });
    } catch {
      updateCurrentRollout(run, { personalChat: "failed" });
    }
  }

  async function walkAssistantBindings(
    run: RolloutState
  ): Promise<"completed" | "stopped" | "failed" | "stale"> {
    let cursor: string | null = null;
    while (isCurrentRollout(run)) {
      let chunk: AssistantFleetAdvancePublic;
      try {
        chunk = await data.eneo.skills.organization.advanceAssistants({
          skillId: run.skillId,
          expected_published_revision_id: run.publishedRevisionId,
          cursor
        });
      } catch {
        updateCurrentRollout(run, { status: "failed" });
        return "failed";
      }
      if (!isCurrentRollout(run)) return "stale";
      addAssistantChunk(run, chunk);
      if (!isCurrentRollout(run) || rollout === null) return "stale";
      if (rollout.stopRequested) {
        updateCurrentRollout(run, { status: "stopped" });
        return "stopped";
      }
      if (chunk.next_cursor === null) {
        return "completed";
      }
      cursor = chunk.next_cursor;
    }
    return "stale";
  }

  async function runPublishedBindingUpdate(run: RolloutState, pinnedRevisionId: string | null) {
    const [, assistantStatus] = await Promise.all([
      advanceReviewedPersonalChat(run, pinnedRevisionId),
      walkAssistantBindings(run)
    ]);
    if (!isCurrentRollout(run)) return;
    if (assistantStatus === "completed") {
      updateCurrentRollout(run, { status: "completed" });
    }
    await refreshOrganizationSkills(run.skillId);
  }

  function startPublishedBindingUpdate(
    skillId: string,
    publishedRevisionId: string,
    previousPublishedRevisionId: string | null,
    adoption: ReviewedAdoption
  ) {
    const summary = adoption.status === "loaded" ? adoption.page.summary : null;
    const personalChat = summary?.personal_chat;
    const pinnedRevisionId =
      personalChat !== undefined &&
      personalChat !== null &&
      personalChat.revision_id !== publishedRevisionId
        ? personalChat.revision_id
        : null;
    const provisionalTotal =
      summary?.revision_counts.reduce(
        (total, revision) =>
          revision.revision_id === publishedRevisionId ? total : total + revision.assistant_count,
        0
      ) ?? 0;
    const run: RolloutState = {
      generation: ++rolloutGeneration,
      skillId,
      publishedRevisionId,
      previousPublishedRevisionId,
      stopRequested: false,
      status: "running",
      provisionalTotal,
      advanced: 0,
      concurrentChange: 0,
      activationUnavailable: 0,
      contextWindow: 0,
      personalChat:
        adoption.status === "unavailable" || summary === null
          ? "failed"
          : pinnedRevisionId === null
            ? "not_applicable"
            : "pending"
    };
    rollout = run;
    void runPublishedBindingUpdate(run, pinnedRevisionId);
  }

  function stopPublishedBindingUpdate() {
    if (rollout === null || rollout.status !== "running") return;
    rollout = { ...rollout, stopRequested: true };
  }

  function startSavedBindingUpdate(adoption: SkillAdoptionProjectionPagePublic) {
    const publishedRevisionId = data.published?.revision_id;
    if (
      publishedRevisionId === undefined ||
      rolloutMutationInFlight ||
      executionBlock.block !== null
    ) {
      return;
    }
    startPublishedBindingUpdate(data.skill.id, publishedRevisionId, null, {
      status: "loaded",
      page: adoption
    });
  }

  function restartPublishedBindingUpdate() {
    const prior = rollout;
    const currentPublishedRevisionId = data.published?.revision_id ?? null;
    if (
      prior === null ||
      (prior.status !== "stopped" && prior.status !== "failed") ||
      prior.personalChat === "pending" ||
      data.skill.id !== prior.skillId ||
      (currentPublishedRevisionId !== prior.publishedRevisionId &&
        currentPublishedRevisionId !== prior.previousPublishedRevisionId)
    ) {
      return;
    }
    const run: RolloutState = {
      ...prior,
      generation: ++rolloutGeneration,
      stopRequested: false,
      status: "running",
      provisionalTotal: Math.max(prior.provisionalTotal - prior.advanced, 0),
      advanced: 0,
      concurrentChange: 0,
      activationUnavailable: 0,
      contextWindow: 0
    };
    rollout = run;
    void (async () => {
      const assistantStatus = await walkAssistantBindings(run);
      if (!isCurrentRollout(run)) return;
      if (assistantStatus === "completed") {
        updateCurrentRollout(run, { status: "completed" });
      }
      await refreshOrganizationSkills(run.skillId);
    })();
  }

  function setExecutionDialogOpen(open: boolean) {
    if (open || executionSaving) return;
    executionAction = null;
    executionError = null;
    executionReason = "";
  }

  function formatExecutionDate(value: string): string {
    return new Date(value).toLocaleString(getLocale() === "sv" ? "sv-SE" : "en-US", {
      dateStyle: "medium",
      timeStyle: "short"
    });
  }

  function setExecutionBlockOverride(block: SkillExecutionBlockState) {
    executionBlockOverrideBase = data.executionBlock;
    executionBlockOverride = block;
  }

  async function reloadExecutionBlock() {
    const block = await data.eneo.settings.getSkillExecutionBlock({
      skillId: data.skill.id
    });
    setExecutionBlockOverride(block);
  }

  async function changeExecution(event: MouseEvent) {
    event.preventDefault();
    if (executionAction === null || executionSaving || normalizedExecutionReason.length === 0) {
      return;
    }
    executionSaving = true;
    executionError = null;
    try {
      if (executionAction === "block") {
        const block = await data.eneo.settings.blockSkillExecution({
          skillId: data.skill.id,
          reason: normalizedExecutionReason
        });
        setExecutionBlockOverride(block);
      } else {
        const reviewedBlock = executionBlock.block;
        if (reviewedBlock === null) {
          await reloadExecutionBlock();
          executionError = m.organization_skills_execution_stale_error();
          executionSaving = false;
          return;
        }
        const block = await data.eneo.settings.unblockSkillExecution({
          skillId: data.skill.id,
          expectedBlockId: reviewedBlock.id,
          reason: normalizedExecutionReason
        });
        setExecutionBlockOverride(block);
      }
    } catch (error) {
      executionError = getErrorMessage(error);
      if (error instanceof EneoError && error.code === SKILL_EXECUTION_BLOCK_CONFLICT) {
        try {
          await reloadExecutionBlock();
        } catch {
          // The conflict message points at the state shown below, so say so
          // plainly when that state could not be refreshed.
          executionError = m.organization_skills_execution_refresh_error();
        }
      }
      executionSaving = false;
      return;
    }
    executionAction = null;
    executionReason = "";
    executionSaving = false;
    await refreshOrganizationSkills();
  }

  async function changePublication(event: MouseEvent) {
    event.preventDefault();
    if (publicationAction === null || publicationSaving || rolloutMutationInFlight) return;
    const skill = data.skill;
    const action = publicationAction;
    const updateBindings = action === "publish" && updateBindingsOnPublish;
    const previousPublishedRevisionId = data.published?.revision_id ?? null;
    let adoption: ReviewedAdoption = { status: "unavailable" };
    publicationSaving = true;
    publicationError = null;
    if (updateBindings) {
      try {
        adoption = { status: "loaded", page: await data.adoptionPage };
      } catch {
        try {
          adoption = {
            status: "loaded",
            page: await getOrganizationSkillAdoption(skill.id, { limit: 1, cursor: null })
          };
        } catch {
          adoption = { status: "unavailable" };
        }
      }
      if (!isCurrentSkill(skill.id)) return;
    }
    try {
      if (action === "publish") {
        await data.eneo.skills.organization.publish({
          skillId: skill.id,
          expected_revision_id: skill.current_revision_id
        });
      } else {
        await data.eneo.skills.organization.unpublish({ skillId: skill.id });
      }
    } catch (error) {
      if (!isCurrentSkill(skill.id)) return;
      publicationError = getErrorMessage(error, m.organization_skills_publication_error());
      publicationSaving = false;
      return;
    }
    if (!isCurrentSkill(skill.id)) return;
    publicationAction = null;
    publicationSaving = false;
    if (updateBindings) {
      startPublishedBindingUpdate(
        skill.id,
        skill.current_revision_id,
        previousPublishedRevisionId,
        adoption
      );
      return;
    }
    await refreshOrganizationSkills(skill.id);
  }

  function openAdvanceDialog(pinned: { revisionId: string; revisionNumber: number }) {
    if (data.published === null) return;
    advancePinned = {
      ...pinned,
      skillId: data.skill.id,
      publishedRevisionId: data.published.revision_id
    };
  }

  // SvelteKit reuses this component across skillId navigations; everything the
  // administrator reviewed belongs to the previous Skill and must not survive.
  let advanceObservedSkillId = untrack(() => data.skill.id);
  $effect(() => {
    const nextSkillId = data.skill.id;
    if (nextSkillId !== advanceObservedSkillId) {
      advanceObservedSkillId = nextSkillId;
      rolloutGeneration += 1;
      rollout = null;
      publicationAction = null;
      publicationSaving = false;
      publicationError = null;
      advancePinned = null;
      advanceError = null;
      advanceAnnouncement = "";
      return;
    }
    if (rollout !== null && !isCurrentRollout(rollout)) {
      rolloutGeneration += 1;
      rollout = null;
    }
  });

  const onAdvancePersonalChat = $derived(
    data.published !== null && executionBlock.block === null && !rolloutMutationInFlight
      ? openAdvanceDialog
      : undefined
  );
  const onStartBindingUpdate = $derived(
    data.published !== null && executionBlock.block === null && !rolloutMutationInFlight
      ? startSavedBindingUpdate
      : undefined
  );

  function setAdvanceDialogOpen(open: boolean) {
    if (open || advanceSaving) return;
    advancePinned = null;
    advanceError = null;
  }

  async function advancePersonalChat(event: MouseEvent) {
    event.preventDefault();
    const pinned = advancePinned;
    if (pinned === null || advanceSaving) return;
    advanceSaving = true;
    advanceError = null;
    let movedToVersion: number;
    try {
      const advance = await data.eneo.skills.organization.advancePersonalChat({
        skillId: pinned.skillId,
        expected_pinned_revision_id: pinned.revisionId,
        expected_published_revision_id: pinned.publishedRevisionId
      });
      movedToVersion = advance.to_revision_number;
    } catch (error) {
      advanceSaving = false;
      if (!isCurrentSkill(pinned.skillId)) return;
      advanceError = getErrorMessage(error, m.organization_skills_advance_error());
      return;
    }
    advanceSaving = false;
    if (!isCurrentSkill(pinned.skillId)) return;
    advancePinned = null;
    advanceAnnouncement = "";
    await tick();
    advanceAnnouncement = m.organization_skills_advance_announcement({
      version: String(movedToVersion)
    });
    await refreshOrganizationSkills();
  }

  beforeNavigate((navigation) => {
    if (formDirty && !confirm(m.unsaved_changes_warning())) {
      navigation.cancel();
    }
  });
</script>

<svelte:head>
  <title>{m.skills_library_edit_page_title({ name: pageTitle })}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: m.skills(),
        href: "/spaces/organization/skills"
      }}
      title={pageTitle}
    ></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-6xl flex-col gap-8 px-4 py-6 sm:px-6 sm:py-8">
      {#if refreshWarning}
        <Alert.Root>
          <Info aria-hidden="true" />
          <Alert.Title>{m.skills_form_saved_status()}</Alert.Title>
          <Alert.Description>
            {m.organization_skills_refresh_after_mutation_warning()}
          </Alert.Description>
          <Alert.Action>
            <Button
              variant="ghost"
              size="icon-sm"
              title={m.reload()}
              aria-label={m.reload()}
              onclick={() => window.location.reload()}
            >
              <RefreshCw aria-hidden="true" />
            </Button>
          </Alert.Action>
        </Alert.Root>
      {/if}
      <div class="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div class="flex min-w-0 flex-col gap-10">
          <section class="flex flex-col gap-5" aria-labelledby="organization-skill-content-heading">
            <div class="flex flex-col gap-1">
              <h2
                id="organization-skill-content-heading"
                class="text-foreground text-lg font-semibold"
              >
                {m.skills_library_content_heading()}
              </h2>
              <p class="text-muted-foreground max-w-[65ch] text-sm leading-6">
                {m.organization_skills_content_description()}
              </p>
            </div>
            <Alert.Root role="note">
              <Info aria-hidden="true" />
              <Alert.Title>{m.skills_library_revision_notice_title()}</Alert.Title>
              <Alert.Description>
                {m.skills_library_revision_notice_description()}
              </Alert.Description>
            </Alert.Root>
            {#key data.skill.current_revision_id}
              <SkillForm
                mode="revision"
                initialValue={{
                  display_name: data.skill.current_revision.display_name,
                  description: data.skill.current_revision.description,
                  instructions: data.skill.current_revision.instructions
                }}
                submitLabel={m.save()}
                submittingLabel={m.saving()}
                onSubmit={createRevision}
                showDiscardAction
                onDirtyChange={(dirty) => (formDirty = dirty)}
              />
            {/key}
          </section>

          {#if approvedPreview && data.skill.published_revision_number !== data.skill.current_revision_number}
            <section aria-labelledby="organization-skill-approved-heading">
              <div class="flex flex-col gap-1">
                <h2
                  id="organization-skill-approved-heading"
                  class="text-foreground text-lg font-semibold"
                >
                  {m.organization_skills_approved_snapshot_heading()}
                </h2>
                <p class="text-muted-foreground max-w-[65ch] text-sm leading-6">
                  {m.organization_skills_approved_snapshot_description()}
                </p>
              </div>
              <div class="mt-4">
                <SkillPreview preview={approvedPreview} />
              </div>
            </section>
          {/if}
        </div>

        <aside
          class="border-border border-t pt-6 lg:sticky lg:top-6 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0"
          aria-labelledby="organization-skill-publication-heading"
        >
          <div class="flex flex-col gap-5">
            <div class="flex flex-col items-start gap-2">
              <div>
                <h2
                  id="organization-skill-publication-heading"
                  class="text-foreground font-semibold"
                >
                  {m.organization_skills_publication_heading()}
                </h2>
                <p class="text-muted-foreground mt-1 max-w-[32ch] text-sm leading-6">
                  {m.organization_skills_publication_description()}
                </p>
              </div>
              <Badge
                variant={publicationVariant(data.skill)}
                class="max-w-full whitespace-normal text-left"
              >
                {publicationLabel(data.skill)}
              </Badge>
            </div>

            <dl class="grid grid-cols-2 gap-x-4 gap-y-3 text-sm lg:grid-cols-1">
              <div>
                <dt class="text-muted-foreground">
                  {m.organization_skills_current_revision_label()}
                </dt>
                <dd class="mt-1 font-medium">
                  {m.organization_skills_version({
                    version: String(data.skill.current_revision_number)
                  })}
                </dd>
              </div>
              <div>
                <dt class="text-muted-foreground">
                  {m.organization_skills_approved_revision_label()}
                </dt>
                <dd class="mt-1 font-medium">
                  {data.skill.published_revision_number === null
                    ? m.organization_skills_not_published()
                    : m.organization_skills_version({
                        version: String(data.skill.published_revision_number)
                      })}
                </dd>
              </div>
            </dl>

            {#if data.skill.publication_state === "update_pending"}
              <div class="flex gap-2" role="note">
                <Info class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
                <div class="min-w-0">
                  <p class="text-sm font-medium">
                    {m.organization_skills_update_pending_title()}
                  </p>
                  <p class="text-muted-foreground mt-1 text-sm leading-6">
                    {m.organization_skills_update_pending_description()}
                  </p>
                </div>
              </div>
            {/if}

            <div class="flex flex-wrap items-center gap-2">
              {#if data.skill.publication_state !== "published"}
                <Button
                  disabled={formDirty || rolloutMutationInFlight}
                  onclick={() => openPublicationDialog("publish")}
                >
                  <ShieldCheck aria-hidden="true" />
                  {data.skill.publication_state === "update_pending"
                    ? m.organization_skills_publish_update_action()
                    : m.organization_skills_publish_action()}
                </Button>
              {/if}
              {#if data.skill.publication_state === "published" || data.skill.publication_state === "update_pending"}
                <Button
                  variant="outline"
                  disabled={formDirty || rolloutMutationInFlight}
                  onclick={() => openPublicationDialog("unpublish")}
                >
                  {m.organization_skills_unpublish_action()}
                </Button>
              {/if}
              {#if formDirty}
                <p class="text-muted-foreground basis-full text-xs">
                  {m.organization_skills_save_before_publication()}
                </p>
              {/if}
            </div>

            {#if data.skill.first_published_at !== null}
              <section
                class="border-border flex flex-col gap-4 border-t pt-5"
                aria-labelledby="organization-skill-execution-heading"
              >
                <div class="flex flex-col items-start gap-2">
                  <div>
                    <h2
                      id="organization-skill-execution-heading"
                      class="text-foreground font-semibold"
                    >
                      {m.organization_skills_execution_heading()}
                    </h2>
                    <p class="text-muted-foreground mt-1 max-w-[32ch] text-sm leading-6">
                      {m.organization_skills_execution_description()}
                    </p>
                  </div>
                  <Badge variant={executionBlock.block === null ? "outline" : "destructive"}>
                    {executionBlock.block === null
                      ? m.organization_skills_execution_available_status()
                      : m.organization_skills_execution_blocked_status()}
                  </Badge>
                </div>

                {#if executionBlock.block}
                  <Alert.Root variant="destructive">
                    <ShieldAlert aria-hidden="true" />
                    <Alert.Title>{m.organization_skills_execution_blocked_status()}</Alert.Title>
                    <Alert.Description>
                      <span class="block">
                        {m.organization_skills_execution_blocked_description()}
                      </span>
                      <span class="mt-2 block font-medium text-current">
                        {executionBlock.block.reason}
                      </span>
                      <span class="mt-1 block text-xs text-current/80">
                        {m.organization_skills_execution_blocked_at({
                          time: formatExecutionDate(executionBlock.block.blocked_at)
                        })}
                      </span>
                    </Alert.Description>
                  </Alert.Root>
                {/if}

                <div>
                  <Button
                    variant={executionBlock.block === null ? "destructive" : "outline"}
                    onclick={() =>
                      (executionAction = executionBlock.block === null ? "block" : "unblock")}
                  >
                    {#if executionBlock.block === null}
                      <ShieldAlert aria-hidden="true" />
                      {m.organization_skills_execution_block_action()}
                    {:else}
                      <ShieldCheck aria-hidden="true" />
                      {m.organization_skills_execution_unblock_action()}
                    {/if}
                  </Button>
                </div>
              </section>
            {/if}
          </div>
        </aside>
      </div>

      {#await data.adoptionPage}
        <SkillAdoptionProjection
          skillId={data.skill.id}
          initialPage={null}
          initialLoading
          {getOrganizationSkillAdoption}
          {onAdvancePersonalChat}
          publishedRevisionId={data.published?.revision_id ?? null}
          {onStartBindingUpdate}
          run={rollout}
          onStop={stopPublishedBindingUpdate}
          onRestart={restartPublishedBindingUpdate}
        />
      {:then adoptionPage}
        <SkillAdoptionProjection
          skillId={data.skill.id}
          initialPage={adoptionPage}
          {getOrganizationSkillAdoption}
          {onAdvancePersonalChat}
          publishedRevisionId={data.published?.revision_id ?? null}
          {onStartBindingUpdate}
          run={rollout}
          onStop={stopPublishedBindingUpdate}
          onRestart={restartPublishedBindingUpdate}
        />
        <p class="sr-only" aria-live="polite">{advanceAnnouncement}</p>
      {:catch}
        <SkillAdoptionProjection
          skillId={data.skill.id}
          initialPage={null}
          initialError
          {getOrganizationSkillAdoption}
          {onAdvancePersonalChat}
          publishedRevisionId={data.published?.revision_id ?? null}
          {onStartBindingUpdate}
          run={rollout}
          onStop={stopPublishedBindingUpdate}
          onRestart={restartPublishedBindingUpdate}
        />
        <p class="sr-only" aria-live="polite">{advanceAnnouncement}</p>
      {/await}

      <section aria-labelledby="organization-skill-history-heading">
        <h2
          id="organization-skill-history-heading"
          class="text-foreground mb-1 text-lg font-semibold"
        >
          {m.skills_library_history_heading()}
        </h2>
        <p class="text-muted-foreground mb-4 max-w-[65ch] text-sm leading-6">
          {m.skills_library_history_description()}
        </p>
        <p class="sr-only" aria-live="polite">{restoreAnnouncement}</p>
        {#key data.skill.current_revision_id}
          <SkillRevisionHistory
            currentRevision={data.skill.current_revision}
            initialPage={data.revisionPage}
            canRestore
            hasUnsavedChanges={formDirty}
            onLoadMore={loadMoreRevisions}
            onView={getRevision}
            onRestore={restoreRevision}
            onLoadCurrent={loadCurrentRevision}
            onAnnounce={announceRestore}
            onRestored={refreshAfterRestore}
          />
        {/key}
      </section>
    </div>
  </Page.Main>
</Page.Root>

<AlertDialog.Root open={publicationAction !== null} onOpenChange={setPublicationDialogOpen}>
  <AlertDialog.Content class={publicationAction === "publish" ? "sm:max-w-md" : undefined}>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {publicationAction === "unpublish"
          ? m.organization_skills_unpublish_title()
          : m.organization_skills_publish_title()}
      </AlertDialog.Title>
      <AlertDialog.Description>
        {publicationAction === "unpublish"
          ? m.organization_skills_unpublish_description()
          : m.organization_skills_publish_description({
              revision: String(data.skill.current_revision_number)
            })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    {#if publicationAction === "publish"}
      <Field.Field orientation="horizontal" class="border-border rounded-lg border p-3">
        <Checkbox
          id="update-bindings-on-publish"
          bind:checked={updateBindingsOnPublish}
          disabled={publicationSaving}
          aria-describedby="update-bindings-on-publish-description"
        />
        <Field.Content>
          <Field.Label for="update-bindings-on-publish">
            {m.organization_skills_publish_update_bindings_label()}
          </Field.Label>
          <Field.Description id="update-bindings-on-publish-description">
            {m.organization_skills_publish_update_bindings_description()}
          </Field.Description>
        </Field.Content>
      </Field.Field>
    {/if}
    {#if publicationError}
      <Alert.Root variant="destructive">
        <Alert.Title>{m.organization_skills_publication_error_title()}</Alert.Title>
        <Alert.Description>{publicationError}</Alert.Description>
      </Alert.Root>
    {/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={publicationSaving}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        variant={publicationAction === "unpublish" ? "destructive" : "default"}
        disabled={publicationSaving}
        onclick={changePublication}
      >
        {publicationSaving
          ? m.saving()
          : publicationAction === "unpublish"
            ? m.organization_skills_unpublish_action()
            : m.organization_skills_publish_action()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root open={advancePinned !== null} onOpenChange={setAdvanceDialogOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.organization_skills_advance_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.organization_skills_advance_description({
          pinned: String(advancePinned?.revisionNumber ?? ""),
          published: String(data.skill.published_revision_number ?? "")
        })}
      </AlertDialog.Description>
    </AlertDialog.Header>
    {#if advanceError}
      <Alert.Root variant="destructive">
        <Alert.Title>{m.organization_skills_advance_error_title()}</Alert.Title>
        <Alert.Description>{advanceError}</Alert.Description>
      </Alert.Root>
    {/if}
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={advanceSaving}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action disabled={advanceSaving} onclick={advancePersonalChat}>
        {advanceSaving ? m.saving() : m.organization_skills_advance_confirm()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root open={executionAction !== null} onOpenChange={setExecutionDialogOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {executionAction === "unblock"
          ? m.organization_skills_execution_unblock_title()
          : m.organization_skills_execution_block_title()}
      </AlertDialog.Title>
      <AlertDialog.Description>
        {executionAction === "unblock"
          ? m.organization_skills_execution_unblock_description()
          : m.organization_skills_execution_block_description()}
      </AlertDialog.Description>
    </AlertDialog.Header>

    {#if executionAction === "unblock" && executionBlock.block}
      <div class="border-border bg-muted/40 rounded-lg border p-3">
        <p class="text-sm font-medium">{m.organization_skills_execution_blocked_status()}</p>
        <p class="text-muted-foreground mt-1 text-sm leading-5">
          {executionBlock.block.reason}
        </p>
      </div>
    {/if}

    <Field.Group>
      <Field.Field>
        <Field.Label for="execution-change-reason">
          {m.organization_skills_execution_reason_label()}
        </Field.Label>
        <Textarea
          id="execution-change-reason"
          bind:value={executionReason}
          required
          maxlength={1000}
          rows={4}
          placeholder={m.organization_skills_execution_reason_placeholder()}
          disabled={executionSaving}
        />
        <Field.Description>
          {executionAction === "unblock"
            ? m.organization_skills_execution_unblock_reason_description()
            : m.organization_skills_execution_block_reason_description()}
        </Field.Description>
      </Field.Field>
    </Field.Group>

    {#if executionError}
      <Alert.Root variant="destructive">
        <Alert.Title>{m.organization_skills_execution_change_error_title()}</Alert.Title>
        <Alert.Description>{executionError}</Alert.Description>
      </Alert.Root>
    {/if}

    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={executionSaving}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        variant={executionAction === "block" ? "destructive" : "default"}
        disabled={executionSaving ||
          normalizedExecutionReason.length === 0 ||
          (executionAction === "unblock" && executionBlock.block === null)}
        onclick={changeExecution}
      >
        {executionSaving
          ? m.saving()
          : executionAction === "unblock"
            ? m.organization_skills_execution_unblock_confirm()
            : m.organization_skills_execution_block_confirm()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
