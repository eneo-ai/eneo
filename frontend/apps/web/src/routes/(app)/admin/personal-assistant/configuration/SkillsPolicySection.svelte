<script lang="ts">
  import type { AssistantSkillBindingInput, AssistantSkillBindingSummary } from "@eneo/eneo-js";
  import { BookOpenCheck } from "lucide-svelte";
  import { resolve } from "$app/paths";
  import { Button } from "$lib/components/ui/button/index.js";
  import SkillBindingsEditor from "$lib/features/skills/SkillBindingsEditor.svelte";
  import type {
    GetSkillBindingPreview,
    ListSkillBindingCatalog,
    SkillBindingCatalogPage
  } from "$lib/features/skills/skillBindingCatalog";
  import { m } from "$lib/paraglide/messages";
  import PolicySection from "$lib/features/admin/PolicySection.svelte";

  type Props = {
    skillBindings: AssistantSkillBindingInput[];
    initialCatalogPage: SkillBindingCatalogPage;
    bindingSummaries: AssistantSkillBindingSummary[];
    summary: string;
    skillsValid: boolean;
    selectiveActivationEnabled: boolean;
    badgeVariant: (enabled: boolean, valid: boolean) => "default" | "outline" | "destructive";
    onListCatalog: ListSkillBindingCatalog;
    onGetSkillPreview: GetSkillBindingPreview;
  };

  let {
    skillBindings = $bindable(),
    initialCatalogPage,
    bindingSummaries,
    summary,
    skillsValid,
    selectiveActivationEnabled,
    badgeVariant,
    onListCatalog,
    onGetSkillPreview
  }: Props = $props();
</script>

<PolicySection
  id="skills"
  title={m.governance_skills_heading()}
  description={m.governance_skills_section_description()}
  {summary}
  summaryVariant={badgeVariant(skillBindings.length > 0, skillsValid)}
>
  {#snippet icon()}
    <BookOpenCheck class="size-5" />
  {/snippet}

  <div class="space-y-5">
    <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
      <p class="text-muted-foreground max-w-[65ch] text-sm leading-6" role="note">
        <span class="text-foreground font-medium">{m.governance_skills_scope_title()}</span>.
        {m.governance_skills_scope_description()}
      </p>

      <Button
        href={resolve("/spaces/organization/skills")}
        variant="outline"
        class="shrink-0 self-start"
      >
        {m.governance_manage_skills_action()}
      </Button>
    </div>

    <SkillBindingsEditor
      bind:bindings={skillBindings}
      {initialCatalogPage}
      {bindingSummaries}
      canEditBindings={true}
      canCreateSkills={false}
      activationSurface="personal_chat"
      {selectiveActivationEnabled}
      {onListCatalog}
      {onGetSkillPreview}
    />
  </div>
</PolicySection>
