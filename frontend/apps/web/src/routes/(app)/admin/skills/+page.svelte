<script lang="ts">
  import type { SkillRuntimePolicyUpdate } from "@eneo/eneo-js";
  import ArrowRight from "lucide-svelte/icons/arrow-right";
  import BookOpenCheck from "lucide-svelte/icons/book-open-check";
  import SlidersHorizontal from "lucide-svelte/icons/sliders-horizontal";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo.js";
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import SkillRuntimePolicySettings from "$lib/features/skills/SkillRuntimePolicySettings.svelte";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { untrack } from "svelte";

  const eneo = getEneo();
  let { data } = $props();

  // The badge mirrors the last saved policy, so track it across saves/resets.
  let selectiveEnabled = $state(
    untrack(() => data.skillRuntimePolicy.selective_activation_enabled)
  );

  async function saveSkillRuntimePolicy(policy: SkillRuntimePolicyUpdate) {
    const updatedPolicy = await eneo.settings.updateSkillRuntimePolicy(policy);
    const modelProjections = await eneo.settings
      .getSkillRuntimeModelProjections()
      .catch(() => null);
    selectiveEnabled = updatedPolicy.selective_activation_enabled;
    return { policy: updatedPolicy, modelProjections };
  }

  async function resetSkillRuntimePolicy() {
    const policy = await eneo.settings.resetSkillRuntimePolicy();
    const modelProjections = await eneo.settings
      .getSkillRuntimeModelProjections()
      .catch(() => null);
    selectiveEnabled = policy.selective_activation_enabled;
    return { policy, modelProjections };
  }
</script>

<svelte:head>
  <title>{m.admin_skills_page_title()}</title>
</svelte:head>

<div class="flex h-full min-w-0 flex-grow flex-col overflow-hidden">
  <div class="border-default bg-primary border-b">
    <div class="px-6 pt-5 pb-5">
      <h1 class="text-primary text-xl font-bold">{m.admin_skills_title()}</h1>
      <p class="text-secondary mt-0.5 text-sm">
        {m.admin_skills_subtitle()}
      </p>
    </div>
  </div>

  <div class="flex min-h-0 flex-1 flex-col overflow-y-auto px-6 pt-6">
    <div class="mx-auto w-full max-w-4xl space-y-6 pb-24">
      <PolicySection
        id="skill-runtime"
        title={m.skills_runtime_policy_title()}
        description={m.skills_runtime_policy_description()}
        summary={selectiveEnabled
          ? m.admin_skills_runtime_summary_on()
          : m.admin_skills_runtime_summary_off()}
        summaryVariant={selectiveEnabled ? "default" : "outline"}
      >
        {#snippet icon()}
          <SlidersHorizontal class="h-5 w-5" aria-hidden="true" />
        {/snippet}
        <SkillRuntimePolicySettings
          initialPolicy={data.skillRuntimePolicy}
          initialModelProjections={data.skillRuntimeModelProjections}
          onSave={saveSkillRuntimePolicy}
          onReset={resetSkillRuntimePolicy}
        />
      </PolicySection>

      <PolicySection
        id="skill-catalogue"
        title={m.admin_skills_catalogue_title()}
        description={m.admin_skills_catalogue_description()}
        summary={m.admin_skills_catalogue_summary()}
        summaryVariant="outline"
      >
        {#snippet icon()}
          <BookOpenCheck class="h-5 w-5" aria-hidden="true" />
        {/snippet}
        <div class="flex flex-col gap-4">
          <p class="text-secondary max-w-[75ch] text-sm leading-6">
            {m.admin_skills_catalogue_bindings_note()}
          </p>
          <div class="flex flex-wrap gap-2">
            <Button href={localizeHref("/spaces/organization/skills")}>
              {m.governance_manage_skills_action()}
              <ArrowRight data-icon="inline-end" aria-hidden="true" />
            </Button>
            <Button variant="outline" href={localizeHref("/admin/personal-assistant")}>
              {m.admin_skills_open_personal_assistant()}
            </Button>
          </div>
        </div>
      </PolicySection>
    </div>
  </div>
</div>
