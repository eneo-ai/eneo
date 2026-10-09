<!--
  The organisation's document templates, on the File creation capability card: the Word
  files assistants' Word and PDF files are rendered into. One is the default; Eneo's own
  template applies until one is uploaded, and can be downloaded to adapt in Word.
-->
<script lang="ts">
  import type { Eneo, components } from "@eneo/eneo-js";
  import {
    Check,
    ChevronDown,
    ChevronUp,
    Download,
    FileText,
    Pencil,
    RefreshCw,
    Star,
    Trash2,
    TriangleAlert,
    Upload
  } from "@lucide/svelte";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { toastError } from "$lib/core/errors";
  import FileDropzone from "$lib/features/attachments/components/FileDropzone.svelte";
  import type { AcceptedFormat } from "$lib/features/attachments/AttachmentManager";
  import { m } from "$lib/paraglide/messages";

  type DocumentTemplate = components["schemas"]["DocumentTemplatePublic"];
  type Placeholder = components["schemas"]["TemplatePlaceholderPublic"];

  let {
    templates,
    runtimeConfigured = false,
    eneo,
    onchange
  }: {
    /** null when the backend predates document templates. */
    templates: DocumentTemplate[] | null;
    runtimeConfigured?: boolean;
    eneo: Eneo;
    onchange: () => Promise<void>;
  } = $props();

  const uid = $props.id();
  const DOCX: AcceptedFormat = {
    mimetype: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    maxSize: 5 * 1024 * 1024,
    extensions: [".docx"]
  };
  // Field names the runtime fills from the document itself; the rest the assistant supplies.
  const AUTO_FIELDS = new Set([
    "title",
    "titel",
    "rubrik",
    "date",
    "datum",
    "year",
    "år",
    "organisation",
    "organization",
    "organisationen",
    "author",
    "författare",
    "forfattare"
  ]);
  const CHECK_LABELS: Record<string, () => string> = {
    content_placeholder: m.document_template_check_content_placeholder,
    heading_styles: m.document_template_check_heading_styles,
    title_style: m.document_template_check_title_style,
    list_styles: m.document_template_check_list_styles,
    table_style: m.document_template_check_table_style,
    language: m.document_template_check_language
  };

  let uploadOpen = $state(false);
  let uploadName = $state("");
  let uploadFile = $state<File | null>(null);
  let uploadDefault = $state(false);
  let renaming = $state<DocumentTemplate | null>(null);
  let renameValue = $state("");
  let replacing = $state<DocumentTemplate | null>(null);
  let replaceFile = $state<File | null>(null);
  let deleting = $state<DocumentTemplate | null>(null);
  let expanded = $state<string | null>(null);
  let busy = $state<string | null>(null);

  const hasDefault = $derived((templates ?? []).some((t) => t.is_default));

  function warnings(template: DocumentTemplate): number {
    return Object.values(template.checks).filter((check) => !check.ok).length;
  }

  function fieldKind(placeholder: Placeholder): string {
    if (!placeholder.supported) return m.document_template_field_unsupported();
    const name = placeholder.name.toLowerCase();
    const content = ["content", "dokument", "innehåll", "innehall", "body"].includes(name);
    if (content) return "";
    return AUTO_FIELDS.has(name)
      ? m.document_template_field_auto()
      : m.document_template_field_assistant();
  }

  function fields(template: DocumentTemplate): Placeholder[] {
    const seen: Record<string, true> = {};
    return template.placeholders.filter((p) => {
      if (seen[p.name]) return false;
      seen[p.name] = true;
      return true;
    });
  }

  function openUpload() {
    uploadName = "";
    uploadFile = null;
    uploadDefault = !hasDefault;
    uploadOpen = true;
  }

  async function upload() {
    if (!uploadFile) throw new Error(m.document_template_file());
    const name = uploadName.trim() || uploadFile.name.replace(/\.docx$/i, "");
    await eneo.documentTemplates.upload({ file: uploadFile, name, isDefault: uploadDefault });
    await onchange();
  }

  async function rename() {
    if (!renaming) return;
    await eneo.documentTemplates.update({
      id: renaming.id,
      update: { name: renameValue.trim() }
    });
    await onchange();
  }

  async function replace() {
    if (!replacing || !replaceFile) throw new Error(m.document_template_file());
    await eneo.documentTemplates.replaceContent({ id: replacing.id, file: replaceFile });
    await onchange();
  }

  async function remove() {
    if (!deleting) return;
    await eneo.documentTemplates.delete({ id: deleting.id });
    await onchange();
  }

  async function makeDefault(template: DocumentTemplate) {
    busy = template.id;
    try {
      await eneo.documentTemplates.update({ id: template.id, update: { is_default: true } });
      await onchange();
    } catch (error) {
      toastError(error, m.document_template_could_not_save());
    } finally {
      busy = null;
    }
  }

  async function download(blob: Promise<Blob>, filename: string) {
    try {
      const url = URL.createObjectURL(await blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (error) {
      toastError(error, m.document_template_could_not_download());
    }
  }
</script>

<div class="border-dimmer border-t p-5">
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div class="min-w-0">
      <h3 class="text-default font-medium" id={`${uid}-title`}>{m.document_templates()}</h3>
      <p class="text-secondary mt-1 max-w-[64ch] text-sm">{m.document_templates_description()}</p>
    </div>
    {#if templates !== null}
      <Button size="sm" variant="outline" onclick={openUpload}>
        <Upload class="size-4" aria-hidden="true" />{m.document_template_upload()}
      </Button>
    {/if}
  </div>

  {#if templates === null}
    <p class="text-secondary mt-3 text-sm">{m.document_template_not_supported()}</p>
  {:else}
    {#if templates.length === 0}
      <p class="text-secondary mt-3 text-sm">{m.document_template_empty()}</p>
    {/if}
    <ul class="border-default mt-3 divide-y rounded-lg border" aria-labelledby={`${uid}-title`}>
      {#each templates as template (template.id)}
        {@const count = warnings(template)}
        <li class="px-4 py-3">
          <div class="flex items-center gap-3">
            <FileText class="text-secondary size-5 shrink-0" aria-hidden="true" />
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <span class="text-default truncate font-medium">{template.name}</span>
                {#if template.is_default}
                  <span
                    class="bg-accent-dimmer text-accent-stronger rounded-full px-2 py-0.5 text-xs font-medium"
                    >{m.document_template_default()}</span
                  >
                {/if}
                {#if template.status === "unchecked"}
                  <span
                    class="bg-secondary text-secondary rounded-full px-2 py-0.5 text-xs font-medium"
                    title={m.document_template_unchecked()}>{m.document_template_unchecked()}</span
                  >
                {:else if template.status === "invalid" || count > 0}
                  <span
                    class="bg-warning-dimmer text-warning-stronger inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
                  >
                    <TriangleAlert class="size-3" aria-hidden="true" />
                    {template.status === "invalid"
                      ? m.document_template_invalid()
                      : m.document_template_warnings({ count })}
                  </span>
                {/if}
              </div>
              <p class="text-secondary mt-0.5 text-sm">
                {template.filename} · {formatBytes(template.size_bytes)}
                {#if template.selected_by > 0}
                  · {m.document_template_selected_by({ count: template.selected_by })}
                {/if}
              </p>
            </div>
            <button
              type="button"
              class="text-secondary hover:bg-hover-dimmer rounded-md px-2 py-1 text-sm"
              aria-expanded={expanded === template.id}
              aria-controls={`${uid}-checks-${template.id}`}
              onclick={() => (expanded = expanded === template.id ? null : template.id)}
            >
              {expanded === template.id
                ? m.document_template_hide_checks()
                : m.document_template_show_checks()}
              {#if expanded === template.id}
                <ChevronUp class="ml-1 inline size-3.5" aria-hidden="true" />
              {:else}
                <ChevronDown class="ml-1 inline size-3.5" aria-hidden="true" />
              {/if}
            </button>
            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                {#snippet child({ props })}
                  <Button
                    {...props}
                    variant="ghost"
                    size="icon"
                    disabled={busy === template.id}
                    aria-label={`${m.actions()}: ${template.name}`}
                  >
                    <IconEllipsis />
                  </Button>
                {/snippet}
              </DropdownMenu.Trigger>
              <DropdownMenu.Content align="end">
                {#if !template.is_default}
                  <DropdownMenu.Item onSelect={() => makeDefault(template)}>
                    <Star class="size-4" aria-hidden="true" />{m.document_template_make_default()}
                  </DropdownMenu.Item>
                {/if}
                <DropdownMenu.Item
                  onSelect={() => {
                    renaming = template;
                    renameValue = template.name;
                  }}
                >
                  <Pencil class="size-4" aria-hidden="true" />{m.document_template_rename()}
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  onSelect={() => {
                    replacing = template;
                    replaceFile = null;
                  }}
                >
                  <RefreshCw
                    class="size-4"
                    aria-hidden="true"
                  />{m.document_template_replace_file()}
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  onSelect={() =>
                    download(
                      eneo.documentTemplates.downloadContent({ id: template.id }),
                      template.filename
                    )}
                >
                  <Download class="size-4" aria-hidden="true" />{m.document_template_download()}
                </DropdownMenu.Item>
                <DropdownMenu.Item variant="destructive" onSelect={() => (deleting = template)}>
                  <Trash2 class="size-4" aria-hidden="true" />{m.document_template_delete()}
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          </div>
          {#if expanded === template.id}
            <div
              id={`${uid}-checks-${template.id}`}
              class="bg-secondary mt-3 rounded-lg p-3 text-sm"
            >
              {#if template.status === "unchecked"}
                <p class="text-secondary">{m.document_template_unchecked()}</p>
              {:else}
                <p class="text-default font-medium">{m.document_template_checks()}</p>
                <ul class="mt-1 space-y-1">
                  {#each Object.entries(template.checks) as [name, check] (name)}
                    <li class="flex items-start gap-2">
                      {#if check.ok}
                        <Check
                          class="text-positive-default mt-0.5 size-4 shrink-0"
                          aria-hidden="true"
                        />
                      {:else}
                        <TriangleAlert
                          class="text-warning-stronger mt-0.5 size-4 shrink-0"
                          aria-hidden="true"
                        />
                      {/if}
                      <span>
                        <span class="text-default">{(CHECK_LABELS[name] ?? (() => name))()}</span>
                        <span class="text-secondary"> · {check.detail}</span>
                      </span>
                    </li>
                  {/each}
                </ul>
                <p class="text-default mt-3 font-medium">{m.document_template_fields()}</p>
                {#if fields(template).length === 0}
                  <p class="text-secondary mt-1">{m.document_template_no_fields()}</p>
                {:else}
                  <ul class="mt-1 space-y-0.5">
                    {#each fields(template) as placeholder (placeholder.name)}
                      {@const kind = fieldKind(placeholder)}
                      <li class="text-secondary">
                        <code class="text-default">{placeholder.name}</code>
                        {#if placeholder.label && placeholder.label !== placeholder.name}
                          <span> ({placeholder.label})</span>
                        {/if}
                        {#if kind}
                          <span> · {kind}</span>
                        {/if}
                        {#if placeholder.hint}
                          <span class="block pl-4 text-xs">{placeholder.hint}</span>
                        {/if}
                      </li>
                    {/each}
                  </ul>
                {/if}
              {/if}
            </div>
          {/if}
        </li>
      {/each}
      <li class="px-4 py-3">
        <div class="flex items-center gap-3">
          <FileText class="text-secondary size-5 shrink-0" aria-hidden="true" />
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-default font-medium">{m.document_template_builtin_name()}</span>
              {#if !hasDefault}
                <span
                  class="bg-accent-dimmer text-accent-stronger rounded-full px-2 py-0.5 text-xs font-medium"
                  >{m.document_template_default()}</span
                >
              {/if}
            </div>
            <p class="text-secondary mt-0.5 text-sm">{m.document_template_builtin_description()}</p>
          </div>
          <Button
            size="sm"
            variant="ghost"
            disabled={!runtimeConfigured}
            onclick={() =>
              download(
                eneo.documentTemplates.downloadBuiltin({ language: "sv" }),
                "eneo-dokumentmall.docx"
              )}
          >
            <Download class="size-4" aria-hidden="true" />{m.document_template_download()}
          </Button>
        </div>
      </li>
    </ul>
  {/if}
</div>

<ConfirmDialog
  bind:open={uploadOpen}
  title={m.document_template_upload()}
  confirmLabel={m.document_template_save()}
  pendingLabel={m.document_template_saving()}
  variant="default"
  width="medium"
  errorDisplay="inline"
  errorContext={m.document_template_could_not_save()}
  confirmDisabled={uploadFile === null}
  onConfirm={upload}
>
  <div class="flex flex-col gap-4">
    <FileDropzone
      formats={[DOCX]}
      multiple={false}
      description={m.document_template_file()}
      onselect={({ accepted }) => {
        uploadFile = accepted[0] ?? null;
        if (uploadFile && !uploadName) uploadName = uploadFile.name.replace(/\.docx$/i, "");
      }}
    />
    <Field.Field>
      <Field.Label for={`${uid}-upload-name`}>{m.document_template_name()}</Field.Label>
      <Input id={`${uid}-upload-name`} bind:value={uploadName} maxlength={120} />
    </Field.Field>
    <Field.Field orientation="horizontal">
      <Field.Label for={`${uid}-upload-default`}
        >{m.document_template_make_default_switch()}</Field.Label
      >
      <Switch id={`${uid}-upload-default`} bind:checked={uploadDefault} />
    </Field.Field>
  </div>
</ConfirmDialog>

<ConfirmDialog
  open={renaming !== null}
  title={m.document_template_rename()}
  confirmLabel={m.document_template_save()}
  pendingLabel={m.document_template_saving()}
  variant="default"
  errorDisplay="inline"
  errorContext={m.document_template_could_not_save()}
  confirmDisabled={renameValue.trim().length === 0}
  onConfirm={async () => {
    await rename();
    renaming = null;
  }}
>
  <Field.Field>
    <Field.Label for={`${uid}-rename`}>{m.document_template_name()}</Field.Label>
    <Input id={`${uid}-rename`} bind:value={renameValue} maxlength={120} />
  </Field.Field>
</ConfirmDialog>

<ConfirmDialog
  open={replacing !== null}
  title={m.document_template_replace_file()}
  description={replacing?.name}
  confirmLabel={m.document_template_save()}
  pendingLabel={m.document_template_saving()}
  variant="default"
  width="medium"
  errorDisplay="inline"
  errorContext={m.document_template_could_not_save()}
  confirmDisabled={replaceFile === null}
  onConfirm={async () => {
    await replace();
    replacing = null;
  }}
>
  <FileDropzone
    formats={[DOCX]}
    multiple={false}
    description={m.document_template_file()}
    onselect={({ accepted }) => (replaceFile = accepted[0] ?? null)}
  />
</ConfirmDialog>

<ConfirmDialog
  open={deleting !== null}
  title={m.document_template_delete()}
  description={m.document_template_delete_confirmation()}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.document_template_could_not_delete()}
  onConfirm={async () => {
    await remove();
    deleting = null;
  }}
>
  <p class="text-default font-semibold">{deleting?.name}</p>
</ConfirmDialog>
