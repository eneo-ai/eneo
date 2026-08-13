<script lang="ts">
  import { beforeNavigate, goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import SkillForm from "$lib/features/skills/SkillForm.svelte";
  import type { SkillFormValue } from "$lib/features/skills/skillBindings";
  import { m } from "$lib/paraglide/messages";
  import { CheckCircle2, Info } from "lucide-svelte";

  let { data } = $props();

  let formDirty = $state(false);
  let allowNavigation = $state(false);
  let createdSkillHref = $state<string | null>(null);

  async function createSkill(value: SkillFormValue) {
    const skill = await data.eneo.skills.organization.create(value);
    const skillHref = resolve(`/spaces/organization/skills/${skill.id}`);
    createdSkillHref = skillHref;
    formDirty = false;
    allowNavigation = true;
    try {
      await goto(skillHref);
    } catch {
      // Creation is already committed. Keep a non-repeatable success state with
      // a direct link instead of reporting the mutation as failed.
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
    <div class="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8">
      <div class="max-w-[65ch]">
        <h2 class="text-foreground text-base font-semibold">
          {m.organization_skills_new_heading()}
        </h2>
        <p class="text-muted-foreground mt-1 text-sm leading-6">
          {m.organization_skills_new_intro()}
        </p>
      </div>
      {#if createdSkillHref}
        <Alert.Root>
          <CheckCircle2 aria-hidden="true" />
          <Alert.Title>{m.organization_skills_created_title()}</Alert.Title>
          <Alert.Description>
            {m.organization_skills_created_navigation_failed_description()}
          </Alert.Description>
          <Button class="mt-3" href={createdSkillHref} variant="outline">
            {m.organization_skills_open_created_action()}
          </Button>
        </Alert.Root>
      {:else}
        <Alert.Root role="note">
          <Info aria-hidden="true" />
          <Alert.Title>{m.organization_skills_draft_notice_title()}</Alert.Title>
          <Alert.Description>{m.organization_skills_draft_notice_description()}</Alert.Description>
        </Alert.Root>
        <SkillForm
          onSubmit={createSkill}
          showDiscardAction
          onDirtyChange={(dirty) => (formDirty = dirty)}
        />
      {/if}
    </div>
  </Page.Main>
</Page.Root>
