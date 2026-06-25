<script lang="ts">
  import { Input } from "@intric/ui";
  import { SvelteSet } from "svelte/reactivity";
  import { m } from "$lib/paraglide/messages";
  import type {
    MetadataFieldType,
    ResourceMetadataJson,
    TenantMetadataField
  } from "@intric/intric-js";

  type ResourceType = "assistant" | "space";

  type EditableRow = {
    id: string;
    key: string;
    fieldType: MetadataFieldType;
    value: string | number | boolean | undefined;
  };

  let {
    metadataJson = null,
    tenantFields = [],
    resourceType,
    onChange
  }: {
    metadataJson?: ResourceMetadataJson | null;
    tenantFields?: TenantMetadataField[];
    resourceType: ResourceType;
    onChange: (value: ResourceMetadataJson | null) => void;
  } = $props();

  let editableRows = $state<EditableRow[]>([]);
  let lastPropSignature = $state<string | null>(null);
  let preservedRoot = $state<Record<string, unknown>>({});
  let preservedEneoEntries = $state<unknown[]>([]);

  function visibleForResource(field: TenantMetadataField) {
    return resourceType === "assistant" ? field.visible_on_assistants : field.visible_on_spaces;
  }

  function isValueCompatible(value: unknown, fieldType: MetadataFieldType) {
    if (fieldType === "boolean") return typeof value === "boolean";
    if (fieldType === "string") return typeof value === "string";
    if (fieldType === "int") return typeof value === "number" && Number.isInteger(value);
    return false;
  }

  function nextRowId() {
    return `${Math.random().toString(36).slice(2)}-${Date.now()}`;
  }

  function isMetadataEntry(value: unknown): value is {
    key: string;
    value: unknown;
    type: MetadataFieldType;
  } {
    if (!value || typeof value !== "object") return false;

    const entry = value as Record<string, unknown>;
    return (
      typeof entry.key === "string" &&
      (entry.type === "string" || entry.type === "int" || entry.type === "boolean")
    );
  }

  function serializeRows(rows: EditableRow[]) {
    const next: Record<string, unknown> = { ...preservedRoot };
    const eneoEntries = [...preservedEneoEntries];

    for (const row of rows) {
      if (!row.key.trim()) continue;
      if (row.value === undefined) continue;
      eneoEntries.push({
        key: row.key.trim(),
        value: row.value,
        type: row.fieldType
      });
    }

    if (eneoEntries.length > 0) {
      next.eneo = eneoEntries;
    }

    return Object.keys(next).length > 0 ? (next as ResourceMetadataJson) : null;
  }

  function emitChange(rows = editableRows) {
    const serialized = serializeRows(rows);
    lastPropSignature = JSON.stringify(serialized);
    onChange(serialized);
  }

  function buildRows() {
    const current = metadataJson ?? {};
    const applicableTenantFields = tenantFields.filter(visibleForResource);
    const allTenantFieldsByName = new Map(tenantFields.map((field) => [field.name, field]));
    const visibleTenantFieldsByName = new Map(
      applicableTenantFields.map((field) => [field.name, field])
    );
    const usedKeys = new SvelteSet<string>();

    const nextEditableRows: EditableRow[] = [];
    const nextPreservedRoot: Record<string, unknown> = {};
    const nextPreservedEneoEntries: unknown[] = [];

    for (const [key, value] of Object.entries(current)) {
      if (key === "eneo") continue;
      nextPreservedRoot[key] = value;
    }

    const eneoEntries = Array.isArray(current.eneo) ? current.eneo : [];

    for (const rawEntry of eneoEntries) {
      if (!isMetadataEntry(rawEntry)) {
        nextPreservedEneoEntries.push(rawEntry);
        continue;
      }

      const tenantField = visibleTenantFieldsByName.get(rawEntry.key);
      if (
        tenantField &&
        rawEntry.type === tenantField.field_type &&
        isValueCompatible(rawEntry.value, tenantField.field_type)
      ) {
        nextEditableRows.push({
          id: nextRowId(),
          key: rawEntry.key,
          fieldType: tenantField.field_type,
          value: rawEntry.value as string | number | boolean
        });
        usedKeys.add(rawEntry.key);
      } else if (!allTenantFieldsByName.has(rawEntry.key)) {
        nextPreservedEneoEntries.push(rawEntry);
      }
    }

    for (const field of applicableTenantFields) {
      if (usedKeys.has(field.name)) continue;
      nextEditableRows.push({
        id: nextRowId(),
        key: field.name,
        fieldType: field.field_type,
        value: undefined
      });
    }

    editableRows = nextEditableRows;
    preservedRoot = nextPreservedRoot;
    preservedEneoEntries = nextPreservedEneoEntries;
  }

  $effect(() => {
    const nextSignature = JSON.stringify(metadataJson ?? null);
    if (nextSignature === lastPropSignature) {
      return;
    }
    lastPropSignature = nextSignature;
    buildRows();
  });

  function updateRow(rowId: string, patch: Partial<EditableRow>) {
    editableRows = editableRows.map((row) => (row.id === rowId ? { ...row, ...patch } : row));
    emitChange();
  }

  function valueText(row: EditableRow) {
    if (row.fieldType === "string") return typeof row.value === "string" ? row.value : "";
    if (row.fieldType === "int") return typeof row.value === "number" ? String(row.value) : "";
    return "";
  }

  function updateTextValue(row: EditableRow, raw: string) {
    if (row.fieldType === "string") {
      updateRow(row.id, { value: raw.trim() === "" ? undefined : raw });
      return;
    }

    if (row.fieldType === "int") {
      if (raw.trim() === "") {
        updateRow(row.id, { value: undefined });
        return;
      }

      const parsed = Number.parseInt(raw, 10);
      if (Number.isNaN(parsed)) return;
      updateRow(row.id, { value: parsed });
    }
  }

  function inputId(row: EditableRow) {
    return `resource-metadata-${resourceType}-${row.key}`;
  }
</script>

<div class="space-y-4">
  {#if editableRows.length === 0}
    <p class="text-muted text-sm">{m.resource_metadata_empty()}</p>
  {/if}

  {#each editableRows as row (row.id)}
    <div class="max-w-md space-y-2">
      {#if row.fieldType === "boolean"}
        <Input.Switch
          class="[&>label]:text-muted flex-col items-start gap-2 [&>label]:flex-grow-0 [&>label]:text-xs [&>label]:font-medium [&>label]:tracking-wide [&>label]:uppercase"
          value={row.value === true}
          sideEffect={({ next }) => {
            updateRow(row.id, { value: next });
          }}
        >
          {row.key}
        </Input.Switch>
      {:else}
        <label
          class="text-muted block text-xs font-medium tracking-wide uppercase"
          for={inputId(row)}
        >
          {row.key}
        </label>
        <input
          id={inputId(row)}
          type={row.fieldType === "int" ? "number" : "text"}
          step={row.fieldType === "int" ? "1" : undefined}
          value={valueText(row)}
          class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
          oninput={(event) => {
            const target = event.currentTarget as HTMLInputElement;
            updateTextValue(row, target.value);
          }}
        />
      {/if}
    </div>
  {/each}
</div>
