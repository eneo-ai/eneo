<script lang="ts">
  import PolicySection from "$lib/features/admin/PolicySection.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { m } from "$lib/paraglide/messages";
  import Brain from "lucide-svelte/icons/brain";

  const DEFAULT_VALUE = "default";
  const VALUE_PREFIX = "reasoning:";

  type Props = {
    defaultEffort: string | null;
    allowUserOverride: boolean;
    configured: boolean;
    options: string[];
    summary: string;
    valid: boolean;
    optionLabel: (option: string) => string;
    onActivate: () => void;
  };

  let {
    defaultEffort = $bindable(),
    allowUserOverride = $bindable(),
    configured,
    options,
    summary,
    valid,
    optionLabel,
    onActivate
  }: Props = $props();

  const selectedValue = $derived(
    defaultEffort === null ? DEFAULT_VALUE : `${VALUE_PREFIX}${defaultEffort}`
  );
</script>

<PolicySection
  id="reasoning"
  title={m.governance_reasoning_heading()}
  description={m.governance_reasoning_section_desc()}
  {summary}
  summaryVariant={valid ? "outline" : "destructive"}
>
  {#snippet icon()}
    <Brain class="h-5 w-5" />
  {/snippet}

  {#if !configured}
    <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <p class="text-secondary text-sm">
        {options.length > 0
          ? m.governance_reasoning_activate_help()
          : m.governance_reasoning_no_models()}
      </p>
      <Button type="button" variant="outline" onclick={onActivate} disabled={options.length === 0}>
        {m.governance_reasoning_activate()}
      </Button>
    </div>
  {:else if options.length > 0}
    <div class="grid gap-2 sm:grid-cols-[minmax(0,1fr)_16rem] sm:items-center">
      <div>
        <Label for="reasoning-default">{m.governance_reasoning_default_label()}</Label>
        <p class="text-secondary mt-1 text-sm">{m.governance_reasoning_default_help()}</p>
      </div>
      <Select.Root
        type="single"
        value={selectedValue}
        onValueChange={(value) => {
          defaultEffort = value.startsWith(VALUE_PREFIX) ? value.slice(VALUE_PREFIX.length) : null;
        }}
      >
        <Select.Trigger id="reasoning-default" class="w-full">
          {defaultEffort ? optionLabel(defaultEffort) : m.default_behavior()}
        </Select.Trigger>
        <Select.Content>
          <Select.Item value={DEFAULT_VALUE} label={m.default_behavior()}>
            {m.default_behavior()}
          </Select.Item>
          {#each options as option (option)}
            <Select.Item value={`${VALUE_PREFIX}${option}`} label={optionLabel(option)}>
              {optionLabel(option)}
            </Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
    </div>
  {:else}
    <p class="text-secondary text-sm">{m.governance_reasoning_no_models()}</p>
  {/if}

  <div class="flex items-start justify-between gap-4 border-t pt-4">
    <div>
      <Label for="reasoning-user-override">
        {m.governance_reasoning_user_override_label()}
      </Label>
      <p id="reasoning-user-override-help" class="text-secondary mt-1 text-sm">
        {m.governance_reasoning_user_override_help()}
      </p>
    </div>
    <Switch
      id="reasoning-user-override"
      bind:checked={allowUserOverride}
      aria-describedby="reasoning-user-override-help"
    />
  </div>
</PolicySection>
