<script lang="ts">
  import { beforeNavigate, goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import SkillForm from "$lib/features/skills/SkillForm.svelte";
  import type { SkillFormValue } from "$lib/features/skills/skillBindings";
  import { m } from "$lib/paraglide/messages";
  import ArrowRight from "lucide-svelte/icons/arrow-right";
  import CheckCircle2 from "lucide-svelte/icons/check-circle-2";
  import Info from "lucide-svelte/icons/info";

  let { data } = $props();

  let formDirty = $state(false);
  let allowNavigation = $state(false);
  let createdSkillHref = $state<string | null>(null);

  async function createSkill(value: SkillFormValue) {
    const skill = await data.eneo.skills.organization.create(value);
    const skillHref = resolve("/(app)/spaces/organization/skills/[skillId]", { skillId: skill.id });
    createdSkillHref = skillHref;
    formDirty = false;
    allowNavigation = true;
    try {
      await goto(skillHref);
    } catch {
      // `goto` only rejects when a `beforeNavigate` cancels or a newer
      // navigation supersedes it. The creation is already committed, so keep
      // a non-repeatable success state with a direct link instead of
      // reporting the mutation as failed.
    } finally {
      allowNavigation = false;
    }
  }

  beforeNavigate((navigation) => {
    if (!allowNavigation && formDirty && !confirm(m.unsaved_changes_warning())) {
      navigation.cancel();
    }
  });
</script>

<svelte:head>
  <title>{m.organization_skills_new_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: m.skills(),
        href: "/spaces/organization/skills"
      }}
      title={m.skills_library_new_heading()}
    ></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-[44rem] flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
      <p class="text-muted-foreground max-w-[65ch] text-sm leading-6">
        {m.organization_skills_new_intro()}
      </p>
      {#if createdSkillHref}
        <Alert.Root>
          <CheckCircle2 aria-hidden="true" />
          <Alert.Title>{m.organization_skills_created_title()}</Alert.Title>
          <Alert.Description>
            {m.organization_skills_created_navigation_failed_description()}
          </Alert.Description>
          <div class="col-start-2 mt-2">
            <Button href={createdSkillHref} size="sm">
              {m.organization_skills_open_created_action()}
              <ArrowRight data-icon="inline-end" aria-hidden="true" />
            </Button>
          </div>
        </Alert.Root>
      {:else}
        <Alert.Root role="note">
          <Info aria-hidden="true" />
          <Alert.Title>{m.organization_skills_draft_notice_title()}</Alert.Title>
          <Alert.Description>{m.organization_skills_draft_notice_description()}</Alert.Description>
        </Alert.Root>
        <SkillForm
          class="max-w-none"
          onSubmit={createSkill}
          showDiscardAction
          onDirtyChange={(dirty) => (formDirty = dirty)}
        />
      {/if}
    </div>
  </Page.Main>
</Page.Root>
