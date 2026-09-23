<script lang="ts">
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import { m } from "$lib/paraglide/messages";

  /**
   * One entry point for changing a step with the AI Builder. Each intent opens
   * the Builder on this step with a request already written in the composer;
   * nothing is sent until the user sends it, so the text can be adjusted first.
   */
  let {
    usesAI,
    hasInstruction,
    onRequest
  }: {
    /** The step has an AI instruction (a completion step). */
    usesAI: boolean;
    hasInstruction: boolean;
    /** `undefined` opens the Builder on the step with an empty composer. */
    onRequest: (request?: string) => void;
  } = $props();

  const intents = $derived(
    [
      usesAI && {
        key: "instruction",
        label: hasInstruction
          ? m.flow_step_ai_menu_improve_instruction()
          : m.flow_step_ai_menu_write_instruction(),
        description: m.flow_step_ai_menu_instruction_desc(),
        request: hasInstruction
          ? m.flow_step_ai_request_improve_instruction()
          : m.flow_step_ai_request_write_instruction()
      },
      {
        key: "underlag",
        label: m.flow_step_ai_menu_underlag(),
        description: m.flow_step_ai_menu_underlag_desc(),
        request: m.flow_step_ai_request_underlag()
      },
      usesAI && {
        key: "format",
        label: m.flow_step_ai_menu_format(),
        description: m.flow_step_ai_menu_format_desc(),
        request: m.flow_step_ai_request_format()
      }
    ].filter((intent) => intent !== false)
  );
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="outline" size="sm">
        {m.flow_step_change_with_ai()}
        <ChevronDown data-icon="inline-end" aria-hidden="true" />
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end" class="w-80">
    <DropdownMenu.Group>
      {#each intents as intent (intent.key)}
        <DropdownMenu.Item
          class="flex-col items-start gap-0.5 py-2 whitespace-normal"
          onclick={() => onRequest(intent.request)}
        >
          <span class="text-primary text-sm font-medium">{intent.label}</span>
          <span class="text-secondary text-xs leading-relaxed">{intent.description}</span>
        </DropdownMenu.Item>
      {/each}
    </DropdownMenu.Group>
    <DropdownMenu.Separator />
    <DropdownMenu.Group>
      <DropdownMenu.Item
        class="flex-col items-start gap-0.5 py-2 whitespace-normal"
        onclick={() => onRequest()}
      >
        <span class="text-primary text-sm font-medium">{m.flow_step_ai_menu_own()}</span>
        <span class="text-secondary text-xs leading-relaxed">{m.flow_step_ai_menu_own_desc()}</span>
      </DropdownMenu.Item>
    </DropdownMenu.Group>
  </DropdownMenu.Content>
</DropdownMenu.Root>
