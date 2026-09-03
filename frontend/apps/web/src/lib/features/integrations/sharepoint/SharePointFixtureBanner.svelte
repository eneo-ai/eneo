<script lang="ts">
  import { ChevronDown, FlaskConical } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";

  type ScenarioOption = { value: string; label: string };

  let {
    scenarios,
    value,
    triggerLabel,
    description,
    disabled = false,
    onValueChange,
    class: className = ""
  }: {
    scenarios: ScenarioOption[];
    value: string;
    triggerLabel: string;
    description: string;
    disabled?: boolean;
    onValueChange: (value: string) => void;
    class?: string;
  } = $props();

  const uid = $props.id();
  let detailsOpen = $state(false);
</script>

<Alert.Root class="border-caution bg-caution {className}">
  <FlaskConical class="text-caution!" aria-hidden="true" />
  <Collapsible.Root bind:open={detailsOpen} class="col-start-2 min-w-0">
    <div class="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-center">
      <div class="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-2">
        <Alert.Title class="text-caution">
          {m.sharepoint_fixture_compact_title()}
        </Alert.Title>
        <span class="text-muted-foreground text-xs">
          {m.sharepoint_fixture_compact_status()}
        </span>
      </div>

      <div class="flex min-w-0 items-center gap-1.5">
        <span id="{uid}-scenario-label" class="sr-only">
          {m.sharepoint_fixture_scenario_label()}
        </span>
        <Select.Root type="single" {value} {onValueChange} {disabled}>
          <Select.Trigger
            class="h-8 min-w-0 flex-1 sm:w-56 sm:flex-none"
            aria-labelledby="{uid}-scenario-label"
          >
            {triggerLabel}
          </Select.Trigger>
          <Select.Content>
            {#each scenarios as scenario (scenario.value)}
              <Select.Item value={scenario.value} label={scenario.label} />
            {/each}
          </Select.Content>
        </Select.Root>

        <Collapsible.Trigger
          class="hover:bg-muted inline-flex h-8 shrink-0 items-center gap-1 rounded-md px-2 text-xs font-medium"
        >
          {m.details()}
          <ChevronDown
            class="size-3.5 transition-transform {detailsOpen ? 'rotate-180' : ''}"
            aria-hidden="true"
          />
        </Collapsible.Trigger>
      </div>
    </div>

    <Collapsible.Content>
      <Alert.Description class="border-caution/25 text-muted-foreground mt-2 border-t pt-2">
        {description}
      </Alert.Description>
    </Collapsible.Content>
  </Collapsible.Root>
</Alert.Root>
