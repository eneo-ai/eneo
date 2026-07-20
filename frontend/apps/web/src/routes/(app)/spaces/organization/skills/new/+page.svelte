<script lang="ts">
  import { beforeNavigate, goto, invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import SkillForm from "$lib/features/skills/SkillForm.svelte";
  import type { SkillFormValue } from "$lib/features/skills/skillBindings";
  import { m } from "$lib/paraglide/messages";
  import { Info } from "lucide-svelte";

  let { data } = $props();

  let formDirty = $state(false);
  let allowNavigation = $state(false);

  async function createSkill(value: SkillFormValue) {
    const skill = await data.eneo.skills.organization.create(value);
    await invalidate("organization:skills");
    allowNavigation = true;
    try {
      await goto(resolve(`/spaces/organization/skills/${skill.id}`));
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
    <div class="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-6">
      <div>
        <h2 class="text-foreground text-lg font-semibold">
          {m.organization_skills_new_heading()}
        </h2>
        <p class="text-muted-foreground mt-1 text-sm leading-6">
          {m.organization_skills_new_intro()}
        </p>
      </div>
      <Alert.Root>
        <Info aria-hidden="true" />
        <Alert.Title>{m.organization_skills_draft_notice_title()}</Alert.Title>
        <Alert.Description>{m.organization_skills_draft_notice_description()}</Alert.Description>
      </Alert.Root>
      <SkillForm
        onSubmit={createSkill}
        showDiscardAction
        onDirtyChange={(dirty) => (formDirty = dirty)}
      />
    </div>
  </Page.Main>
</Page.Root>
