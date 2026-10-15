<script lang="ts">
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import { untrack } from "svelte";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import type { VariablePickerContext } from "$lib/features/flows/components/VariablePicker.svelte";
  import type { JsonObject } from "$lib/features/flows/jsonObject";
  import { m } from "$lib/paraglide/messages";
  import ToolArgumentsJson from "./ToolArgumentsJson.svelte";

  let {
    value,
    namedArguments,
    disabled,
    onChange,
    keptText = null,
    onUnsavedText,
    variableContext
  }: {
    /** The stored arguments the schema does not name. */
    value: JsonObject;
    /** The arguments the schema names, which have rows of their own. */
    namedArguments: string[];
    disabled: boolean;
    onChange: (value: JsonObject) => void;
    keptText?: string | null;
    onUnsavedText?: (text: string | null) => void;
    variableContext?: VariablePickerContext;
  } = $props();

  // Most open schemas never get such arguments, so the field starts folded
  // unless the step holds some or a text not yet saved when it is shown; after
  // that the author's opening and closing stay, also while what they type
  // empties it.
  let open = $state(untrack(() => Object.keys(value).length > 0 || keptText !== null));
</script>

<!-- A text not yet saved keeps the field open, so it stays in view and
     "Gå till steg" can land on it. -->
<Collapsible.Root
  bind:open={() => open || keptText !== null, (next) => (open = next)}
  class="flex flex-col gap-2"
>
  <Collapsible.Trigger
    class="group focus-visible:ring-ring flex min-h-8 w-fit items-center gap-1.5 rounded-sm text-sm font-medium outline-none focus-visible:ring-2"
  >
    <ChevronRight
      class="text-secondary size-3.5 shrink-0 group-data-[state=open]:rotate-90 motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out)"
      aria-hidden="true"
    />
    {m.flow_tool_arguments_other_title()}
  </Collapsible.Trigger>
  <Collapsible.Content>
    <ToolArgumentsJson
      {value}
      {disabled}
      {onChange}
      {keptText}
      {onUnsavedText}
      {variableContext}
      reservedNames={namedArguments}
      label={m.flow_tool_arguments_other_label()}
      hint={m.flow_tool_arguments_other_hint()}
    />
  </Collapsible.Content>
</Collapsible.Root>
