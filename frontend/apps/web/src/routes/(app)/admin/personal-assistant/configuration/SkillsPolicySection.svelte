<script lang="ts">
  import type {
    SkillBindingReferenceInput,
    SkillBindingSummary,
    SkillPublic,
    SkillSparse
  } from "@eneo/eneo-js";
  import { BookOpenCheck, Info } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import SkillBindingsEditor from "$lib/features/skills/SkillBindingsEditor.svelte";
  import type { SkillFormValue } from "$lib/features/skills/skillBindings";
  import { m } from "$lib/paraglide/messages";
  import PolicySection from "./PolicySection.svelte";

  type Props = {
    skillBindings: SkillBindingReferenceInput[];
    availableSkills: SkillSparse[];
    bindingSummaries: SkillBindingSummary[];
    summary: string;
    canEditSkills: boolean;
    canCreateSkills: boolean;
    onCreateSkill: (value: SkillFormValue) => Promise<SkillPublic>;
  };

  let {
    skillBindings = $bindable(),
    availableSkills,
    bindingSummaries,
    summary,
    canEditSkills,
    canCreateSkills,
    onCreateSkill
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

  <SkillBindingsEditor
    bind:bindings={skillBindings}
    {availableSkills}
    {bindingSummaries}
    canEditBindings={canEditSkills}
    {canCreateSkills}
    {onCreateSkill}
  />
</PolicySection>
