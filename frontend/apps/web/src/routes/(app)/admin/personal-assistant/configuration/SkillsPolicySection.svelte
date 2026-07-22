<script lang="ts">
  import type { SkillBindingReferenceInput, SkillBindingSummary } from "@eneo/eneo-js";
  import { BookOpenCheck, Info } from "lucide-svelte";
  import { resolve } from "$app/paths";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import SkillBindingsEditor from "$lib/features/skills/SkillBindingsEditor.svelte";
  import type {
    ListSkillBindingCatalog,
    SkillBindingCatalogPage
  } from "$lib/features/skills/skillBindingCatalog";
  import { m } from "$lib/paraglide/messages";
  import PolicySection from "./PolicySection.svelte";

  type Props = {
    skillBindings: SkillBindingReferenceInput[];
    initialCatalogPage: SkillBindingCatalogPage;
    bindingSummaries: SkillBindingSummary[];
    summary: string;
    canUseSkills: boolean;
    onListCatalog: ListSkillBindingCatalog;
  };

  let {
    skillBindings = $bindable(),
    initialCatalogPage,
    bindingSummaries,
    summary,
    canUseSkills,
    onListCatalog
  }: Props = $props();
</script>

<PolicySection
  id="skills"
  title={m.governance_skills_heading()}
  description={m.governance_skills_section_description()}
  {summary}
  summaryVariant={skillBindings.length > 0 ? "default" : "outline"}
>
  {#snippet icon()}
    <BookOpenCheck class="size-5" />
  {/snippet}

  <Alert.Root>
    <Info aria-hidden="true" />
    <Alert.Title>{m.governance_skills_scope_title()}</Alert.Title>
    <Alert.Description>{m.governance_skills_scope_description()}</Alert.Description>
  </Alert.Root>

  <div class="flex flex-col items-start gap-2">
    <p class="text-muted-foreground text-sm">
      {m.governance_manage_skills_description()}
    </p>
    <Button href={resolve("/spaces/organization/skills")} variant="outline">
      {m.governance_manage_skills_action()}
    </Button>
  </div>

  <SkillBindingsEditor
    bind:bindings={skillBindings}
    {initialCatalogPage}
    {bindingSummaries}
    canEditBindings={canUseSkills}
    canCreateSkills={false}
    {onListCatalog}
  />
</PolicySection>
