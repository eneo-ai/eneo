<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { IconPlus } from "@intric/icons/plus";
  import { IconTrash } from "@intric/icons/trash";
  import { Button } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  export let isPublished: boolean;

  const {
    state: { update }
  } = getFlowEditor();

  type FormField = { name: string; type: string; required?: boolean };

  $: formSchema = $update.metadata_json?.form_schema as { fields: FormField[] } | undefined;

  // Local staging buffer — only syncs to store when all field names are non-empty
  let localFields: FormField[] = [];
  $: localFields = formSchema?.fields ? [...formSchema.fields] : [];

  function addField() {
    localFields = [...localFields, { name: "", type: "text", required: false }];
  }

  function removeField(index: number) {
    localFields = localFields.filter((_, i) => i !== index);
    syncToStore(localFields);
  }

  function updateField(index: number, key: keyof FormField, value: string | boolean) {
    localFields[index] = { ...localFields[index], [key]: value };
    localFields = localFields;
    // Only sync when all names are non-empty
    if (localFields.every((f) => f.name.trim() !== "")) {
      syncToStore(localFields);
    }
  }

  function syncToStore(fields: FormField[]) {
    $update.metadata_json = {
      ...($update.metadata_json ?? {}),
      form_schema: { fields }
    };
  }

  const FIELD_TYPES = ["text", "number", "email", "textarea", "date", "select"];
</script>

<Settings.Group title={m.flow_form_schema()}>
  <p class="text-secondary px-4 -mt-4 text-sm">{m.flow_form_schema_description()}</p>

  {#if localFields.length === 0}
    <div class="px-4 py-6 text-center">
      <p class="text-secondary text-sm">{m.flow_form_schema_empty()}</p>
    </div>
  {/if}

  {#each localFields as field, index}
    <div class="border-default mx-4 mb-3 rounded-lg border p-4">
      <div class="flex items-start justify-between gap-4">
        <div class="flex-1 space-y-3">
          <div>
            <label class="text-sm font-medium">{m.flow_form_field_name()}</label>
            <input
              type="text"
              class="border-default bg-primary ring-default mt-1 w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2"
              placeholder={m.flow_form_field_name()}
              value={field.name}
              disabled={isPublished}
              on:input={(e) => updateField(index, "name", e.currentTarget.value)}
            />
          </div>
          <div class="flex gap-4">
            <div class="flex-1">
              <label class="text-sm font-medium">{m.flow_form_field_type()}</label>
              <select
                class="border-default bg-primary ring-default mt-1 w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2"
                disabled={isPublished}
                value={field.type}
                on:change={(e) => updateField(index, "type", e.currentTarget.value)}
              >
                {#each FIELD_TYPES as t}
                  <option value={t}>{t}</option>
                {/each}
              </select>
            </div>
            <label class="flex items-center gap-2 pt-7 text-sm">
              <input
                type="checkbox"
                checked={field.required ?? false}
                disabled={isPublished}
                on:change={(e) => updateField(index, "required", e.currentTarget.checked)}
              />
              {m.flow_form_field_required()}
            </label>
          </div>
        </div>
        {#if !isPublished}
          <button
            class="text-secondary mt-1 hover:text-red-500"
            on:click={() => removeField(index)}
          >
            <IconTrash class="size-4" />
          </button>
        {/if}
      </div>
    </div>
  {/each}

  {#if !isPublished}
    <div class="px-4 pb-4">
      <Button variant="outlined" class="w-full justify-center" on:click={addField}>
        <IconPlus size="sm" />
        {m.flow_form_add_field()}
      </Button>
    </div>
  {/if}
</Settings.Group>
