<script lang="ts">
  import { beforeNavigate, goto, invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { Page } from "$lib/components/layout";
  import SkillForm from "$lib/features/skills/SkillForm.svelte";
  import type { SkillFormValue } from "$lib/features/skills/skillBindings";
  import { m } from "$lib/paraglide/messages";

  let { data } = $props();

  let formDirty = $state(false);
  let allowNavigation = $state(false);

  const spaceRouteId = $derived(
    data.currentSpace.personal
      ? "personal"
      : data.currentSpace.organization
        ? "organization"
        : data.currentSpace.id
  );

  async function createSkill(value: SkillFormValue) {
    const skill = await data.eneo.skills.create({
      spaceId: data.currentSpace.id,
      ...value
    });
    await invalidate("space:skills");
    allowNavigation = true;
    try {
      await goto(resolve(`/spaces/${spaceRouteId}/skills/${skill.id}`));
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
  <title>{m.skills_library_new_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: m.skills(),
        href: `/spaces/${spaceRouteId}/skills`
      }}
      title={m.skills_library_new_heading()}
    ></Page.Title>
  </Page.Header>
  <Page.Main>
    <div class="mx-auto w-full max-w-3xl px-6 py-6">
      <p class="text-muted-foreground mb-6 text-sm">
        {m.skills_library_new_intro()}
      </p>
      <SkillForm
        onSubmit={createSkill}
        showDiscardAction
        onDirtyChange={(dirty) => (formDirty = dirty)}
      />
    </div>
  </Page.Main>
</Page.Root>
