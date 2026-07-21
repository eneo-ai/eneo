<script lang="ts">
  import type {
    OrganizationSkillPublic,
    PublishedSkillPublic,
    SkillRevisionRestorePublic
  } from "@eneo/eneo-js";
  import { beforeNavigate, invalidate } from "$app/navigation";
  import { Page } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import SkillForm from "$lib/features/skills/SkillForm.svelte";
  import SkillRevisionHistory from "$lib/features/skills/SkillRevisionHistory.svelte";
  import type { SkillRevisionFormValue } from "$lib/features/skills/skillBindings";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { Info, ShieldCheck } from "lucide-svelte";
  import { tick } from "svelte";

  type PublicationAction = "publish" | "unpublish";

  let { data } = $props();

  let formDirty = $state(false);
  let publicationAction = $state<PublicationAction | null>(null);
  let publicationSaving = $state(false);
  let publicationError = $state<string | null>(null);
  let restoreAnnouncement = $state("");

  const pageTitle = $derived(
    data.mode === "manage" ? data.skill.display_name : data.published.display_name
  );

  function managedSkill(): OrganizationSkillPublic {
    if (data.mode !== "manage") {
      throw new Error("Organisation Skill management data is unavailable");
    }
    return data.skill;
  }

  function formatDate(value: string): string {
    return new Date(value).toLocaleString(getLocale() === "sv" ? "sv-SE" : "en-US", {
      dateStyle: "medium",
      timeStyle: "short"
    });
  }

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

  async function createRevision(value: SkillRevisionFormValue) {
    const skill = managedSkill();
    await data.eneo.skills.organization.createRevision({
      skillId: skill.id,
      ...value
    });
    await invalidate("organization:skills");
  }

  async function loadMoreRevisions(cursor: string) {
    const skill = managedSkill();
    return data.eneo.skills.organization.listRevisionSummaries({
      skillId: skill.id,
      cursor
    });
  }

  async function getRevision(revisionId: string) {
    const skill = managedSkill();
    return data.eneo.skills.organization.getRevision({
      skillId: skill.id,
      revisionId
    });
  }

  async function restoreRevision(sourceRevisionId: string) {
    const skill = managedSkill();
    return data.eneo.skills.organization.restoreRevision({
      skillId: skill.id,
      sourceRevisionId
    });
  }

  async function refreshAfterRestore(outcome: SkillRevisionRestorePublic) {
    if (!outcome.created) return;
    await invalidate("organization:skills");
    formDirty = false;
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
    const skill = managedSkill();
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
      publicationAction = null;
      await invalidate("organization:skills");
    } catch (error) {
      publicationError = getErrorMessage(error) || m.organization_skills_publication_error();
    } finally {
      publicationSaving = false;
    }
  }

  beforeNavigate((navigation) => {
    if (formDirty && !confirm(m.unsaved_changes_warning())) {
      navigation.cancel();
    }
  });
</script>

{#snippet publishedPreview(published: PublishedSkillPublic, fullPage = false)}
  <div class={fullPage ? "border-border border-y py-5" : "border-border border-t pt-5"}>
    <div class="flex flex-col gap-4">
      <div class="flex flex-col gap-2">
        <div class="flex flex-wrap items-center gap-2">
          <h3 class="text-foreground font-semibold">{published.display_name}</h3>
          <Badge variant="secondary">{m.organization_skills_status_published()}</Badge>
          <Badge variant="outline">
            {m.organization_skills_version({ version: String(published.revision_number) })}
          </Badge>
        </div>
        <p class="text-muted-foreground max-w-[65ch] text-sm leading-6">
          {published.description}
        </p>
      </div>
      <dl class="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <div class="flex gap-2">
          <dt class="text-muted-foreground">{m.organization_skills_slug_label()}</dt>
          <dd class="font-medium">{published.slug}</dd>
        </div>
        <div class="flex gap-2">
          <dt class="text-muted-foreground">{m.organization_skills_published_at_label()}</dt>
          <dd class="font-medium">{formatDate(published.first_published_at)}</dd>
        </div>
      </dl>
      <div>
        <h4 class="text-foreground mb-2 text-sm font-semibold">
          {m.skills_instructions_label()}
        </h4>
        <div
          class="border-border text-foreground max-h-[32rem] max-w-[75ch] overflow-y-auto border-l-2 pl-4 text-sm leading-6 break-words whitespace-pre-wrap"
        >
          {published.revision.instructions}
        </div>
      </div>
    </div>
  </div>
{/snippet}

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
      {#if data.mode === "browse"}
        <div>
          <h2 class="text-foreground text-lg font-semibold">
            {m.organization_skills_approved_content_heading()}
          </h2>
          <p class="text-muted-foreground mt-1 max-w-[65ch] text-sm leading-6">
            {m.organization_skills_approved_content_description()}
          </p>
        </div>
        {@render publishedPreview(data.published, true)}
      {:else}
        <div class="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <aside
            class="border-border order-first border-b pb-6 lg:order-last lg:sticky lg:top-6 lg:border-b-0 lg:border-l lg:pb-0 lg:pl-6"
            aria-labelledby="organization-skill-publication-heading"
          >
            <div class="flex flex-col gap-4">
              <div class="flex items-start justify-between gap-4">
                <div>
                  <h2
                    id="organization-skill-publication-heading"
                    class="text-foreground font-semibold"
                  >
                    {m.organization_skills_publication_heading()}
                  </h2>
                  <p class="text-muted-foreground mt-1 text-sm leading-6">
                    {m.organization_skills_publication_description()}
                  </p>
                </div>
                <Badge variant={publicationVariant(data.skill)}>
                  {publicationLabel(data.skill)}
                </Badge>
              </div>
              <dl class="grid gap-3 text-sm">
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
                <Alert.Root>
                  <Info aria-hidden="true" />
                  <Alert.Title>{m.organization_skills_update_pending_title()}</Alert.Title>
                  <Alert.Description>
                    {m.organization_skills_update_pending_description()}
                  </Alert.Description>
                </Alert.Root>
              {/if}

              {#if data.canPublish}
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
              {:else}
                <p class="text-muted-foreground text-sm leading-6">
                  {m.organization_skills_admin_publication_only()}
                </p>
              {/if}
            </div>
          </aside>

          <section
            class="flex flex-col gap-5 lg:order-first"
            aria-labelledby="organization-skill-content-heading"
          >
            <div>
              <h2
                id="organization-skill-content-heading"
                class="text-foreground text-lg font-semibold"
              >
                {m.skills_library_content_heading()}
              </h2>
              <p class="text-muted-foreground mt-1 max-w-[65ch] text-sm leading-6">
                {m.organization_skills_content_description()}
              </p>
            </div>
            <Alert.Root>
              <Info aria-hidden="true" />
              <Alert.Title>{m.skills_library_revision_notice_title()}</Alert.Title>
              <Alert.Description>{m.skills_library_revision_notice_description()}</Alert.Description
              >
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
        </div>

        {#if data.published}
          <section aria-labelledby="organization-skill-approved-heading">
            <h2
              id="organization-skill-approved-heading"
              class="text-foreground mb-1 text-lg font-semibold"
            >
              {m.organization_skills_approved_snapshot_heading()}
            </h2>
            <p class="text-muted-foreground mb-4 max-w-[65ch] text-sm leading-6">
              {m.organization_skills_approved_snapshot_description()}
            </p>
            {@render publishedPreview(data.published)}
          </section>
        {/if}

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
              onAnnounce={announceRestore}
              onRestored={refreshAfterRestore}
            />
          {/key}
        </section>
      {/if}
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
              revision: data.mode === "manage" ? String(data.skill.current_revision_number) : ""
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
