<script lang="ts">
  import * as Select from "$lib/components/ui/select/index.js";
  import { getChatService } from "../../ChatService.svelte";
  import { getModelKwargOptionLabel } from "$lib/features/ai-models/ModelKwargCapabilities";
  import { m } from "$lib/paraglide/messages";
  import Brain from "@lucide/svelte/icons/brain";

  const DEFAULT_VALUE = "default";
  const VALUE_PREFIX = "reasoning:";

  const chat = getChatService();
  const options = $derived(chat.settingsResolution?.reasoning_effort_options ?? []);
  const storedEffort = $derived(chat.settings?.reasoning_effort ?? null);
  const effectiveEffort = $derived(chat.settingsResolution?.effective_reasoning_effort ?? null);
  const policyDefaultLabel = $derived.by(() => {
    const policyDefault = chat.settingsResolution?.default_reasoning_effort;
    return policyDefault && options.includes(policyDefault)
      ? getModelKwargOptionLabel(policyDefault)
      : null;
  });
  const selectedValue = $derived(
    storedEffort && options.includes(storedEffort)
      ? `${VALUE_PREFIX}${storedEffort}`
      : DEFAULT_VALUE
  );

  function selectEffort(value: string) {
    const reasoningEffort = value.startsWith(VALUE_PREFIX)
      ? value.slice(VALUE_PREFIX.length)
      : null;
    void chat.updateSettings({ reasoning_effort: reasoningEffort });
  }
</script>

{#if options.length > 0}
  <Select.Root type="single" value={selectedValue} onValueChange={selectEffort}>
    <Select.Trigger
      disabled={chat.settingsBusy ||
        !chat.settings ||
        chat.askQuestion.isLoading ||
        chat.settingsResolution?.settings_compatible === false}
      size="sm"
      class="hover:bg-muted h-8 min-w-0 max-w-40 shrink-0 gap-1 border-transparent bg-transparent px-2 font-medium shadow-none [&>svg:last-child]:hidden @[26rem]/composer:[&>svg:last-child]:block"
      aria-label={`${m.reasoning_effort()}: ${effectiveEffort ? getModelKwargOptionLabel(effectiveEffort) : m.default_behavior()}`}
      title={`${m.reasoning_effort()}: ${effectiveEffort ? getModelKwargOptionLabel(effectiveEffort) : m.default_behavior()}. ${m.reasoning_effort_tooltip()}`}
    >
      <Brain class="size-3.5" aria-hidden="true" />
      <span class="hidden truncate @[36rem]/composer:inline">
        {effectiveEffort ? getModelKwargOptionLabel(effectiveEffort) : m.default_behavior()}
      </span>
    </Select.Trigger>
    <Select.Content align="end">
      <Select.Group>
        <Select.GroupHeading>{m.reasoning_effort()}</Select.GroupHeading>
        <Select.Item value={DEFAULT_VALUE} label={m.governance_reasoning_organization_default()}>
          {m.governance_reasoning_organization_default()}
          {#if policyDefaultLabel}
            <span class="text-muted-foreground">· {policyDefaultLabel}</span>
          {/if}
        </Select.Item>
        {#each options as option (option)}
          <Select.Item value={`${VALUE_PREFIX}${option}`} label={getModelKwargOptionLabel(option)}>
            {getModelKwargOptionLabel(option)}
          </Select.Item>
        {/each}
      </Select.Group>
    </Select.Content>
  </Select.Root>
{/if}
