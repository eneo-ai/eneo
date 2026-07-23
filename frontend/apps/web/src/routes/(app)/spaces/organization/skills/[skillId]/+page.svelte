<script lang="ts">
  import type { OrganizationSkillPublic, SkillRevisionRestorePublic } from "@eneo/eneo-js";
  import { beforeNavigate, invalidate } from "$app/navigation";
  import { Page } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import SkillForm from "$lib/features/skills/SkillForm.svelte";
  import SkillRevisionHistory from "$lib/features/skills/SkillRevisionHistory.svelte";
  import SkillPreview from "$lib/features/skills/SkillPreview.svelte";
  import { publishedSkillPreview } from "$lib/features/skills/skillBindingCatalog";
  import type { SkillRevisionFormValue } from "$lib/features/skills/skillBindings";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { Info, RefreshCw, ShieldCheck } from "lucide-svelte";
  import { tick } from "svelte";

  type PublicationAction = "publish" | "unpublish";

  let { data } = $props();

  let formDirty = $state(false);
  let publicationAction = $state<PublicationAction | null>(null);
  let publicationSaving = $state(false);
  let publicationError = $state<string | null>(null);
  let refreshWarning = $state(false);
  let restoreAnnouncement = $state("");

  const pageTitle = $derived(data.skill.display_name);
  const approvedPreview = $derived(
    data.published === null ? null : publishedSkillPreview(data.published)
  );

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

  async function refreshOrganizationSkills() {
    try {
      await invalidate("organization:skills");
      refreshWarning = false;
    } catch {
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

  async function changePublication(event: MouseEvent) {
    event.preventDefault();
    if (publicationAction === null || publicationSaving) return;
    const skill = data.skill;
    publicationSaving = true;
    publicationError = null;
    try {
      if (publicationAction === "publish") {
        await data.eneo.skills.organization.publish({
          skillId: skill.id,
          expected_revision_id: skill.current_revision_id
        });
      } else {
        await data.eneo.skills.organization.unpublish({ skillId: skill.id });
      }
    } catch (error) {
      publicationError = getErrorMessage(error) || m.organization_skills_publication_error();
      publicationSaving = false;
      return;
    }
    publicationAction = null;
    publicationSaving = false;
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

          {#if approvedPreview}
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
          class="border-border border-t pt-6 lg:sticky lg:top-6 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-8"
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
                <Button disabled={formDirty} onclick={() => (publicationAction = "publish")}>
                  <ShieldCheck aria-hidden="true" />
                  {data.skill.publication_state === "update_pending"
                    ? m.organization_skills_publish_update_action()
                    : m.organization_skills_publish_action()}
                </Button>
              {/if}
              {#if data.skill.publication_state === "published" || data.skill.publication_state === "update_pending"}
                <Button
                  variant="outline"
                  disabled={formDirty}
                  onclick={() => (publicationAction = "unpublish")}
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
          </div>
        </aside>
      </div>

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
  <AlertDialog.Content>
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
