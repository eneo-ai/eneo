<!--
  Copyright (c) 2026 Sundsvalls Kommun

  The space's reader model for digests: inherit the organisation default, pick
  one of the space's own models, or none. The row always says which model
  applies today and why, since the answer depends on the space's security
  classification and the models it has enabled.
-->
<script lang="ts">
  import type { CompletionModel, Space } from "@eneo/eneo-js";
  import { Settings } from "$lib/components/layout";
  import Hint from "$lib/components/Hint.svelte";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { toastError } from "$lib/core/errors";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";

  const INHERIT = "inherit";
  const NONE = "none";

  const {
    state: { currentSpace },
    updateSpace
  } = getSpacesManager();

  type Reader = NonNullable<Space["reader_model"]>;
  const EMPTY_READER: Reader = {
    inherit: true,
    model: null,
    effective: null,
    reason: "none",
    tenant_default: null
  };
  const reader = $derived<Reader>($currentSpace.reader_model ?? EMPTY_READER);
  // The row's options are the space's enabled models: the same list the
  // completion models row manages, already within the space's classification.
  const options = $derived(
    $currentSpace.completion_models.filter(
      (model) => model.is_org_enabled && !model.is_deprecated && !model.migrated_to_model_id
    )
  );
  const disabled = $derived(reader.reason === "no_tool_capable_model");
  const selected = $derived(reader.inherit ? INHERIT : reader.model ? reader.model.id : NONE);
  let saving = $state(false);

  function modelLabel(model: CompletionModel | null | undefined): string {
    return model ? (model.nickname ?? model.name) : "";
  }

  const inheritLabel = $derived(
    reader.tenant_default
      ? m.reader_option_inherit({ model: modelLabel(reader.tenant_default) })
      : m.reader_option_inherit_none()
  );

  const statusText = $derived.by(() => {
    const model = modelLabel(reader.effective ?? reader.tenant_default ?? reader.model);
    switch (reader.reason) {
      case "inherited":
        return m.reader_state_inherited({ model });
      case "own":
        return m.reader_state_own();
      case "policy":
        return m.reader_state_own();
      case "tenant_default_below_classification":
        return m.reader_state_tenant_default_below_classification({ model });
      case "own_below_classification":
        return m.reader_state_own_below_classification({ model });
      case "no_tenant_default":
        return m.reader_state_no_tenant_default();
      case "no_tool_capable_model":
        return m.reader_state_no_tool_capable_model();
      case "policy_disallows":
        return m.reader_state_policy_disallows();
      default:
        return m.reader_state_none();
    }
  });
  const statusTone = $derived(
    reader.reason === "tenant_default_below_classification" ||
      reader.reason === "own_below_classification"
      ? "warning"
      : reader.reason === "inherited" || reader.reason === "own"
        ? "positive"
        : "neutral"
  );

  async function choose(value: string) {
    if (saving || value === selected) return;
    saving = true;
    try {
      if (value === INHERIT) {
        await updateSpace({ reader_model_inherit: true, reader_model: null });
      } else if (value === NONE) {
        await updateSpace({ reader_model_inherit: false, reader_model: null });
      } else {
        await updateSpace({ reader_model_inherit: false, reader_model: { id: value } });
      }
    } catch (e) {
      toastError(e);
    }
    saving = false;
  }
</script>

<Settings.Row title={m.reader_space_heading()} description={m.reader_space_description()}>
  <svelte:fragment slot="description">
    <p class="text-secondary mt-2 text-sm">
      {m.reader_never()}
      {m.reader_space_classification_note()}
    </p>
  </svelte:fragment>

  <div class="flex flex-col gap-3">
    <Label for="space-reader-model">{m.reader_space_label()}</Label>
    <Select.Root
      type="single"
      value={selected}
      onValueChange={choose}
      disabled={disabled || saving}
    >
      <Select.Trigger id="space-reader-model" class="w-full">
        {selected === INHERIT
          ? inheritLabel
          : selected === NONE
            ? m.reader_option_none()
            : modelLabel(reader.model)}
      </Select.Trigger>
      <Select.Content>
        <Select.Item value={INHERIT} label={inheritLabel}>{inheritLabel}</Select.Item>
        <Select.Item value={NONE} label={m.reader_option_none()}
          >{m.reader_option_none()}</Select.Item
        >
        {#each options as model (model.id)}
          <Select.Item value={model.id} label={modelLabel(model)}>{modelLabel(model)}</Select.Item>
        {/each}
      </Select.Content>
    </Select.Root>
    <p
      class="rounded-lg px-3 py-2 text-sm leading-relaxed {statusTone === 'warning'
        ? 'bg-warning-dimmer text-warning-stronger'
        : 'bg-secondary text-primary'}"
      role="status"
    >
      {statusText}
    </p>
    <p class="text-secondary text-sm">{m.reader_space_help()}</p>
    <Hint>{m.reader_space_scope_note()}</Hint>
  </div>
</Settings.Row>
