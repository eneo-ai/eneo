<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { LockKeyhole } from "@lucide/svelte";
  import type { components } from "@eneo/eneo-js";
  import type { CapabilityDescriptor, CapabilityPurpose } from "$lib/features/mcp/capabilities";
  import { modelSupportsToolCalling, readinessMessage } from "$lib/features/mcp/readiness";

  type DocumentTemplateChoice = components["schemas"]["DocumentTemplateChoicePublic"];
  type DocumentTemplateOption = components["schemas"]["DocumentTemplateOptionPublic"];

  let {
    capability,
    selectedModel,
    enabledCapabilities = $bindable([]),
    documentTemplate = $bindable(),
    documentTemplates = []
  }: {
    capability: CapabilityDescriptor;
    selectedModel?: { supports_tool_calling?: boolean } | null;
    enabledCapabilities?: CapabilityPurpose[];
    /** File creation only: which document template the assistant's files follow. */
    documentTemplate?: DocumentTemplateChoice | null;
    /** The organisation's templates, for the choice above. */
    documentTemplates?: DocumentTemplateOption[];
  } = $props();
  const uid = $props.id();
  const {
    state: { currentSpace }
  } = getSpacesManager();
  const on = $derived(enabledCapabilities.includes(capability.purpose));
  const availability = $derived(
    $currentSpace.available_capabilities?.find((c) => c.purpose === capability.purpose)
  );
  const offered = $derived(($currentSpace.enabled_capabilities ?? []).includes(capability.purpose));
  const blockingMessage = $derived(
    !offered
      ? readinessMessage("space_disabled")
      : selectedModel != null && !modelSupportsToolCalling(selectedModel)
        ? readinessMessage("model_no_tool_calling")
        : !availability?.available
          ? readinessMessage(availability?.reason ?? "no_active_provider")
          : ""
  );
  function toggle() {
    enabledCapabilities = on
      ? enabledCapabilities.filter((p) => p !== capability.purpose)
      : [...enabledCapabilities, capability.purpose];
  }

  // The document template choice: only the file-creation row has one.
  const showsTemplate = $derived(capability.purpose === "file_creation" && on);
  const choice = $derived(documentTemplate ?? { mode: "default", template_id: null });
  const defaultTemplate = $derived(documentTemplates.find((t) => t.is_default) ?? null);
  const selectedTemplate = $derived(
    documentTemplates.find((t) => t.id === choice.template_id) ?? null
  );
  let editingTemplate = $state(false);
  const statusText = $derived.by(() => {
    if (choice.mode === "builtin")
      return m.document_template_status({ name: m.document_template_builtin_name() });
    if (choice.mode === "selected" && selectedTemplate)
      return m.document_template_status({ name: selectedTemplate.name });
    return m.document_template_status_default({
      name: defaultTemplate?.name ?? m.document_template_builtin_name()
    });
  });
  function setMode(mode: string) {
    if (mode === "selected") {
      const first = selectedTemplate ?? defaultTemplate ?? documentTemplates[0] ?? null;
      documentTemplate = first
        ? { mode: "selected", template_id: first.id }
        : { mode: "default", template_id: null };
    } else if (mode === "builtin") documentTemplate = { mode: "builtin", template_id: null };
    else documentTemplate = { mode: "default", template_id: null };
  }
  function selectTemplate(id: string) {
    documentTemplate = { mode: "selected", template_id: id };
  }
</script>

<div
  class="border-default border-b px-4 py-3 last:border-b-0 {blockingMessage
    ? 'bg-secondary/40'
    : ''}"
>
  <div class="flex items-center gap-3">
    <capability.icon class="text-muted h-4 w-4 shrink-0" aria-hidden="true" />
    <Field.Field orientation="horizontal" class="min-w-0 flex-1 gap-4">
      <Field.Content class="gap-1">
        <Field.Label for={`${uid}-switch`} class="flex-wrap">
          <span class="font-medium {blockingMessage ? 'text-secondary' : 'text-default'}"
            >{capability.label()}</span
          >
          {#if blockingMessage}
            <span
              class="bg-warning-dimmer text-warning-stronger inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
            >
              <LockKeyhole class="h-3 w-3" aria-hidden="true" />{m.not_available()}
            </span>
          {/if}
        </Field.Label>
        <Field.Description id={`${uid}-hint`} class="text-muted text-xs">
          {blockingMessage || capability.capabilityHint()}
        </Field.Description>
      </Field.Content>
      <Switch
        id={`${uid}-switch`}
        checked={on}
        disabled={!on && !!blockingMessage}
        onCheckedChange={toggle}
        aria-describedby={`${uid}-hint`}
      />
    </Field.Field>
  </div>
  {#if showsTemplate}
    <!-- The template this assistant's Word and PDF files follow; the organisation's default
         unless changed here. Same shape as an attachment's mode row. -->
    <div class="mt-2 ml-7">
      <div class="flex items-center gap-3">
        <p class="text-secondary min-w-0 flex-1 text-sm">{statusText}</p>
        <button
          id={`${uid}-template`}
          type="button"
          class="border-default hover:bg-hover-dimmer shrink-0 rounded-lg border px-3 py-1.5 text-sm"
          aria-expanded={editingTemplate}
          aria-controls={`${uid}-template-options`}
          onclick={() => (editingTemplate = !editingTemplate)}>{m.material_change()}</button
        >
      </div>
      <div
        id={`${uid}-template-options`}
        hidden={!editingTemplate}
        class="bg-secondary mt-2 rounded-lg p-3"
      >
        <RadioGroup.Root
          value={choice.mode}
          onValueChange={setMode}
          aria-labelledby={`${uid}-template`}
          aria-describedby={`${uid}-template-help`}
          class="grid gap-2"
        >
          <Field.Label for={`${uid}-template-default`} class="font-normal">
            <Field.Field orientation="horizontal">
              <RadioGroup.Item value="default" id={`${uid}-template-default`} />
              <span>
                {m.document_template_choice_default()}
                <span class="text-secondary">
                  · {defaultTemplate?.name ?? m.document_template_builtin_name()}</span
                >
              </span>
            </Field.Field>
          </Field.Label>
          <Field.Label for={`${uid}-template-selected`} class="font-normal">
            <Field.Field orientation="horizontal">
              <RadioGroup.Item
                value="selected"
                id={`${uid}-template-selected`}
                disabled={documentTemplates.length === 0}
              />
              <span>{m.document_template_choice_selected()}</span>
            </Field.Field>
          </Field.Label>
          {#if choice.mode === "selected"}
            <select
              class="border-default bg-primary text-default ml-6 rounded-md border px-2 py-1.5 text-sm"
              aria-label={m.document_template_choice_selected()}
              value={choice.template_id ?? ""}
              onchange={(event) => selectTemplate((event.currentTarget as HTMLSelectElement).value)}
            >
              {#each documentTemplates as template (template.id)}
                <option value={template.id}>{template.name}</option>
              {/each}
            </select>
          {:else if documentTemplates.length === 0}
            <p class="text-secondary ml-6 text-xs">{m.document_template_choice_none_available()}</p>
          {/if}
          <Field.Label for={`${uid}-template-builtin`} class="font-normal">
            <Field.Field orientation="horizontal">
              <RadioGroup.Item value="builtin" id={`${uid}-template-builtin`} />
              <span>{m.document_template_choice_builtin()}</span>
            </Field.Field>
          </Field.Label>
        </RadioGroup.Root>
        <p id={`${uid}-template-help`} class="text-secondary mt-2 text-sm">
          {m.document_template_choice_help()}
        </p>
      </div>
    </div>
  {/if}
</div>
