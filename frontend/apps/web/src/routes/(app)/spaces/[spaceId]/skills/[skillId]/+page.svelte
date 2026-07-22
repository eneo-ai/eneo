<script lang="ts">
  import type { ResourcePermission } from "@eneo/eneo-js";
  import { beforeNavigate, invalidate } from "$app/navigation";
  import { Page } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import SkillForm from "$lib/features/skills/SkillForm.svelte";
  import SkillRevisionHistory from "$lib/features/skills/SkillRevisionHistory.svelte";
  import type { SkillRevisionFormValue } from "$lib/features/skills/skillBindings";
  import { m } from "$lib/paraglide/messages";
  import { Info } from "lucide-svelte";
  import { tick } from "svelte";

  const EDIT_SKILL_PERMISSION: ResourcePermission = "edit";

  let { data } = $props();

  let statusError = $state<string | null>(null);
  let statusSaving = $state(false);
  let formDirty = $state(false);
  let restoreAnnouncement = $state("");

  const spaceRouteId = $derived(
    data.currentSpace.personal
      ? "personal"
      : data.currentSpace.organization
        ? "organization"
        : data.currentSpace.id
  );
  const canEdit = $derived(data.currentSpace.skill_permissions.includes(EDIT_SKILL_PERMISSION));

  async function createRevision(value: SkillRevisionFormValue) {
    await data.eneo.skills.createRevision({
      spaceId: data.currentSpace.id,
      skillId: data.skill.id,
      display_name: value.display_name,
      description: value.description,
      instructions: value.instructions
    });
    await invalidate("space:skills");
  }

  async function loadMoreRevisions(cursor: string) {
    return data.eneo.skills.listRevisionSummaries({
      spaceId: data.currentSpace.id,
      skillId: data.skill.id,
      cursor
    });
  }

  async function getRevision(revisionId: string) {
    return data.eneo.skills.getRevision({
      spaceId: data.currentSpace.id,
      skillId: data.skill.id,
      revisionId
    });
  }

  async function restoreRevision(sourceRevisionId: string, reviewedCurrentRevisionId: string) {
    return data.eneo.skills.restoreRevision({
      spaceId: data.currentSpace.id,
      skillId: data.skill.id,
      sourceRevisionId,
      reviewed_current_revision_id: reviewedCurrentRevisionId
    });
  }

  async function loadCurrentRevision() {
    const skill = await data.eneo.skills.get({
      spaceId: data.currentSpace.id,
      skillId: data.skill.id
    });
    return skill.current_revision;
  }

  async function refreshAfterRestore() {
    await invalidate("space:skills");
    formDirty = false;
  }

  async function announceRestore(message: string) {
    restoreAnnouncement = "";
    await tick();
    restoreAnnouncement = message;
  }

  async function setActive(isActive: boolean) {
    statusSaving = true;
    statusError = null;
    try {
      await data.eneo.skills.setActive({
        spaceId: data.currentSpace.id,
        skillId: data.skill.id,
        is_active: isActive
      });
      await invalidate("space:skills");
    } catch (error) {
      const failure = error as { message?: string };
      statusError = failure.message ?? m.skills_library_status_error();
    } finally {
      statusSaving = false;
    }
  }

  beforeNavigate((navigation) => {
    if (formDirty && !confirm(m.unsaved_changes_warning())) {
      navigation.cancel();
    }
  });
</script>

<svelte:head>
  <title>{m.skills_library_edit_page_title({ name: data.skill.display_name })}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: m.skills(),
        href: `/spaces/${spaceRouteId}/skills`
      }}
      title={data.skill.display_name}
    ></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 py-6">
      <Card.Root>
        <Card.Header class="flex-row items-start justify-between gap-4">
          <div>
            <Card.Title>{m.skills_library_status_heading()}</Card.Title>
            <Card.Description>{m.skills_library_status_description()}</Card.Description>
          </div>
          <Badge variant={data.skill.is_active ? "secondary" : "outline"}>
            {data.skill.is_active ? m.skills_active_status() : m.skills_inactive_status()}
          </Badge>
        </Card.Header>
        <Card.Content class="flex flex-col gap-3">
          <p class="text-muted-foreground text-sm">
            {data.skill.is_active
              ? m.skills_library_active_explanation()
              : m.skills_library_inactive_explanation()}
          </p>
          {#if statusError}
            <p class="text-destructive text-sm" role="alert">{statusError}</p>
          {/if}
          {#if canEdit}
            <Button
              variant={data.skill.is_active ? "outline" : "default"}
              disabled={statusSaving}
              onclick={() => setActive(!data.skill.is_active)}
            >
              {statusSaving
                ? m.skills_library_status_saving()
                : data.skill.is_active
                  ? m.skills_library_deactivate()
                  : m.skills_library_activate()}
            </Button>
          {/if}
        </Card.Content>
      </Card.Root>

      <section aria-labelledby="skill-content-heading">
        <h2 id="skill-content-heading" class="text-foreground mb-1 text-lg font-semibold">
          {m.skills_library_content_heading()}
        </h2>
        <p class="text-muted-foreground mb-5 text-sm">
          {canEdit
            ? m.skills_library_content_description()
            : m.skills_library_content_read_only_description()}
        </p>
        {#if canEdit}
          <Alert.Root class="mb-5">
            <Info aria-hidden="true" />
            <Alert.Title>{m.skills_library_revision_notice_title()}</Alert.Title>
            <Alert.Description>{m.skills_library_revision_notice_description()}</Alert.Description>
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
        {:else}
          <Card.Root>
            <Card.Content>
              <dl class="flex flex-col gap-4">
                <div class="flex flex-col gap-1">
                  <dt class="text-muted-foreground text-xs font-medium">{m.name()}</dt>
                  <dd class="text-sm">{data.skill.current_revision.display_name}</dd>
                </div>
                <div class="flex flex-col gap-1">
                  <dt class="text-muted-foreground text-xs font-medium">{m.description()}</dt>
                  <dd class="text-sm">{data.skill.current_revision.description}</dd>
                </div>
                <div class="flex flex-col gap-1">
                  <dt class="text-muted-foreground text-xs font-medium">
                    {m.skills_instructions_label()}
                  </dt>
                  <dd
                    class="border-border bg-muted/25 rounded-md border p-3 text-sm break-words whitespace-pre-wrap"
                  >
                    {data.skill.current_revision.instructions}
                  </dd>
                </div>
              </dl>
            </Card.Content>
          </Card.Root>
        {/if}
      </section>

      <section aria-labelledby="skill-history-heading">
        <h2 id="skill-history-heading" class="text-foreground mb-1 text-lg font-semibold">
          {m.skills_library_history_heading()}
        </h2>
        <p class="text-muted-foreground mb-4 text-sm">
          {m.skills_library_history_description()}
        </p>
        <p class="sr-only" aria-live="polite">{restoreAnnouncement}</p>
        {#key data.skill.current_revision_id}
          <SkillRevisionHistory
            currentRevision={data.skill.current_revision}
            initialPage={data.revisionPage}
            canRestore={canEdit}
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
