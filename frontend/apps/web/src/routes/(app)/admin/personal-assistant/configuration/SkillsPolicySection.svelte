<script lang="ts">
  import type { AssistantSkillBindingInput, AssistantSkillBindingSummary } from "@eneo/eneo-js";
  import BookOpenCheck from "lucide-svelte/icons/book-open-check";
  import Info from "lucide-svelte/icons/info";
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
    canSelectOnDemand: boolean;
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
    canSelectOnDemand,
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
    <div class="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
      <div class="flex items-start gap-3" role="note">
        <Info class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <div class="min-w-0">
          <p class="text-sm font-medium">{m.governance_skills_scope_title()}</p>
          <p class="text-muted-foreground mt-1 max-w-[65ch] text-sm leading-6">
            {m.governance_skills_scope_description()}
          </p>
        </div>
      </div>

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
      supportsActivationModes
      {canSelectOnDemand}
      {selectiveActivationEnabled}
      {onListCatalog}
      {onGetSkillPreview}
    />
  </div>
</PolicySection>
