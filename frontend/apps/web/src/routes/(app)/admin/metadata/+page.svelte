<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Page, Settings } from "$lib/components/layout/index.js";
  import { Button, Input } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric.js";
  import { m } from "$lib/paraglide/messages";
  import { invalidate, invalidateAll } from "$app/navigation";
  import type { MetadataFieldType, TenantMetadataField } from "@intric/intric-js";
  import { untrack } from "svelte";

  let { data } = $props();

  const intric = getIntric();
  const metadataGridClass =
    "grid grid-cols-[minmax(0,1.3fr)_220px_120px_120px_auto] items-end gap-4 rounded-xl border border-[var(--border-color-default)] p-4";
  const typeOptions: Array<{ value: MetadataFieldType; label: string }> = [
    { value: "int", label: m.admin_metadata_type_int() },
    { value: "string", label: m.admin_metadata_type_string() },
    { value: "boolean", label: m.admin_metadata_type_boolean() }
  ];

  type MetadataFieldDraft = {
    id?: string;
    name: string;
    field_type: MetadataFieldType;
    visible_on_assistants: boolean;
    visible_on_spaces: boolean;
  };

  let metadataFields = $state<MetadataFieldDraft[]>(
    untrack(() => (data.settings.metadata_fields ?? []).map(toDraft))
  );

  function toDraft(field: TenantMetadataField): MetadataFieldDraft {
    return {
      id: field.id,
      name: field.name,
      field_type: field.field_type,
      visible_on_assistants: field.visible_on_assistants,
      visible_on_spaces: field.visible_on_spaces
    };
  }

  function createEmptyDraft(): MetadataFieldDraft {
    return {
      name: "",
      field_type: "string",
      visible_on_assistants: true,
      visible_on_spaces: true
    };
  }

  function updateMetadataField(index: number, patch: Partial<MetadataFieldDraft>) {
    metadataFields = metadataFields.map((field, fieldIndex) =>
      fieldIndex === index ? { ...field, ...patch } : field
    );
  }

  function addMetadataField() {
    metadataFields = [...metadataFields, createEmptyDraft()];
  }

  async function saveMetadataField(index: number) {
    const field = metadataFields[index];
    const payload = {
      name: field.name.trim(),
      field_type: field.field_type,
      visible_on_assistants: field.visible_on_assistants,
      visible_on_spaces: field.visible_on_spaces
    };

    if (!payload.name) {
      return;
    }

    const saved = field.id
      ? await intric.settings.updateMetadataField({ id: field.id, ...payload })
      : await intric.settings.createMetadataField(payload);

    metadataFields = metadataFields.map((current, fieldIndex) =>
      fieldIndex === index ? toDraft(saved) : current
    );
    await Promise.all([invalidate("app:settings"), invalidateAll()]);
  }

  async function deleteMetadataField(index: number) {
    const field = metadataFields[index];
    if (!field.id) {
      metadataFields = metadataFields.filter((_, fieldIndex) => fieldIndex !== index);
      return;
    }

    await intric.settings.deleteMetadataField({ id: field.id });
    metadataFields = metadataFields.filter((_, fieldIndex) => fieldIndex !== index);
    await Promise.all([invalidate("app:settings"), invalidateAll()]);
  }

  function fieldInputId(index: number, fieldName: string) {
    return `tenant-metadata-${fieldName}-${index}`;
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.admin_metadata_page_title()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.admin_metadata_page_title()}></Page.Title>
  </Page.Header>
  <Page.Main>
    <Settings.Page>
      <Settings.Group title={m.admin_metadata_group_title()}>
        <Settings.Row
          title={m.admin_metadata_section_title()}
          description={m.admin_metadata_section_description()}
          fullWidth
        >
          <div class="max-w-5xl space-y-4">
            {#each metadataFields as field, index (field.id ?? `new-${index}`)}
              <div class={metadataGridClass}>
                <div class="space-y-2">
                  <label
                    class="text-muted block text-xs font-medium tracking-wide uppercase"
                    for={fieldInputId(index, "key")}>{m.admin_metadata_key_label()}</label
                  >
                  <input
                    id={fieldInputId(index, "key")}
                    type="text"
                    value={field.name}
                    class="border-default bg-primary ring-default rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                    oninput={(event) => {
                      const target = event.currentTarget as HTMLInputElement;
                      updateMetadataField(index, { name: target.value });
                    }}
                  />
                </div>
                <div class="space-y-2">
                  <label
                    class="text-muted block text-xs font-medium tracking-wide uppercase"
                    for={fieldInputId(index, "type")}>{m.type()}</label
                  >
                  <select
                    id={fieldInputId(index, "type")}
                    value={field.field_type}
                    class="border-default bg-primary ring-default rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                    onchange={(event) => {
                      const target = event.currentTarget as HTMLSelectElement;
                      updateMetadataField(index, { field_type: target.value as MetadataFieldType });
                    }}
                  >
                    {#each typeOptions as option (option.value)}
                      <option value={option.value}>{option.label}</option>
                    {/each}
                  </select>
                </div>
                <div class="space-y-2">
                  <Input.Switch
                    class="[&>label]:text-muted flex-col items-center gap-2 [&>label]:flex-grow-0 [&>label]:text-xs [&>label]:font-medium [&>label]:tracking-wide [&>label]:uppercase"
                    value={field.visible_on_assistants}
                    sideEffect={({ next }) =>
                      updateMetadataField(index, { visible_on_assistants: next })}
                  >
                    {m.assistants()}
                  </Input.Switch>
                </div>
                <div class="space-y-2">
                  <Input.Switch
                    class="[&>label]:text-muted flex-col items-center gap-2 [&>label]:flex-grow-0 [&>label]:text-xs [&>label]:font-medium [&>label]:tracking-wide [&>label]:uppercase"
                    value={field.visible_on_spaces}
                    sideEffect={({ next }) =>
                      updateMetadataField(index, { visible_on_spaces: next })}
                  >
                    {m.admin_metadata_spaces_label()}
                  </Input.Switch>
                </div>
                <div class="flex items-end justify-end gap-2 self-stretch">
                  <Button
                    variant="positive-outlined"
                    padding="text"
                    onclick={() => saveMetadataField(index)}>{m.save()}</Button
                  >
                  <Button
                    variant="destructive"
                    padding="text"
                    onclick={() => deleteMetadataField(index)}>{m.delete()}</Button
                  >
                </div>
              </div>
            {/each}

            <div>
              <Button variant="outlined" padding="text" onclick={addMetadataField}
                >{m.admin_metadata_add_field()}</Button
              >
            </div>
          </div>
        </Settings.Row>
      </Settings.Group>
    </Settings.Page>
  </Page.Main>
</Page.Root>
