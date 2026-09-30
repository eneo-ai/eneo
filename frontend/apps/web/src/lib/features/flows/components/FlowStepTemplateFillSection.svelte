<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import { tick } from "svelte";
  import { asset } from "$app/paths";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Spinner } from "$lib/components/ui/spinner/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Empty from "$lib/components/ui/empty/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { IconDownload } from "@eneo/icons/download";
  import { m } from "$lib/paraglide/messages";
  import { getTemplateAssetStatusLabel, getTemplateRowStatusText } from "./flowStepEditHelpers";
  import type {
    FlowTemplateAssetOption,
    FlowTemplateInspection,
    TemplateBindingRow,
    TemplateBindingSuggestionGroup,
    TemplateFillOutputConfig,
    TemplateFillReadiness
  } from "$lib/features/flows/templateFillConfig";

  let {
    isPublished,
    stepKey,
    isAdvancedMode,
    templateFillConfig,
    templateInspection,
    templateInspecting,
    templateConfigError,
    templateCanRetry,
    templateFilesLoading,
    templatePlaceholders,
    templateBindingRows,
    templateBindingSuggestionGroups,
    templateAutoBindings,
    templateReadiness,
    templateOrphanedRows,
    templateHasSelection,
    resolvedTemplateAssetId,
    selectedTemplateAsset,
    templateUnnamedStepWarning,
    templateAutoMatchableCount,
    availableTemplateFiles,
    onOutputModeChange,
    onTemplateFileSelect,
    onTemplateUpload,
    onTemplateRetry,
    onTemplateDownload,
    onTemplateRefresh,
    onBindingChange,
    onApplyAllSuggestions
  }: {
    isPublished: boolean;
    stepKey: string;
    isAdvancedMode: boolean;
    templateFillConfig: TemplateFillOutputConfig;
    templateInspection: FlowTemplateInspection | null;
    templateInspecting: boolean;
    templateConfigError: string | null;
    templateCanRetry: boolean;
    templateFilesLoading: boolean;
    templatePlaceholders: Array<{ name: string }>;
    templateBindingRows: TemplateBindingRow[];
    templateBindingSuggestionGroups: TemplateBindingSuggestionGroup[];
    templateAutoBindings: Record<string, string>;
    templateReadiness: TemplateFillReadiness;
    templateOrphanedRows: TemplateBindingRow[];
    templateHasSelection: boolean;
    resolvedTemplateAssetId: string | null;
    selectedTemplateAsset: FlowTemplateAssetOption | null;
    templateUnnamedStepWarning: boolean;
    templateAutoMatchableCount: number;
    availableTemplateFiles: FlowTemplateAssetOption[];
    onOutputModeChange?: (detail: { value: FlowStep["output_mode"] }) => void;
    onTemplateFileSelect?: (detail: { assetId: string }) => void;
    onTemplateUpload?: (detail: { event: Event }) => void;
    onTemplateRetry?: () => Promise<void>;
    onTemplateDownload?: () => void;
    onTemplateRefresh?: () => void;
    onBindingChange?: (detail: { placeholder: string; value: string }) => void;
    onApplyAllSuggestions?: () => void;
  } = $props();

  const instanceId = $props.id();
  let uploadInput: HTMLInputElement | null = $state(null);
  let templateTrigger: HTMLButtonElement | null = $state(null);
  let retryButton: HTMLButtonElement | null = $state(null);
  const busy = $derived(templateInspecting || templateFilesLoading);
  const cannotEdit = $derived(isPublished);
  const templateAssetValue = $derived(resolvedTemplateAssetId ?? "");
  const templateAssetLabel = $derived(
    selectedTemplateAsset?.name ??
      templateFillConfig.template_name ??
      m.flow_template_fill_select_placeholder()
  );

  function bindingLabel(binding: string | undefined): string {
    if (binding === undefined) return m.flow_template_fill_select_source();
    if (binding === "") return m.flow_template_fill_leave_empty();
    for (const group of templateBindingSuggestionGroups) {
      const match = group.options.find((option) => option.value === binding);
      if (match) return match.label;
    }
    return binding;
  }

  async function retryTemplate() {
    const originKey = stepKey;
    await onTemplateRetry?.();
    await tick();
    if (stepKey !== originKey) return;
    if (templateConfigError) retryButton?.focus();
    else if (!isPublished) {
      const source = document.getElementById(`${instanceId}-source-0`);
      if (source) source.focus();
      else templateTrigger?.focus();
    }
  }
</script>

<div class="flex flex-col gap-6">
  <Card.Root>
    <Card.Header>
      <Card.Title role="heading" aria-level={3}
        >{m.flow_template_fill_template_section()}</Card.Title
      >
      <Card.Description>{m.flow_template_fill_desc()}</Card.Description>
    </Card.Header>
    <Card.Content class="flex flex-col gap-4">
      <Field.FieldGroup>
        <Field.Field>
          <Field.FieldLabel for={`${instanceId}-template`}>
            {m.flow_template_fill_template_label()}
          </Field.FieldLabel>
          <Select.Root
            type="single"
            value={templateAssetValue}
            disabled={cannotEdit || busy}
            onValueChange={(value) => onTemplateFileSelect?.({ assetId: value })}
          >
            <Select.Trigger bind:ref={templateTrigger} id={`${instanceId}-template`} class="w-full">
              <span class="min-w-0 truncate">{templateAssetLabel}</span>
            </Select.Trigger>
            <Select.Content>
              <Select.Group>
                <Select.Item value="" label={m.flow_template_fill_select_placeholder()}>
                  {m.flow_template_fill_select_placeholder()}
                </Select.Item>
                {#each availableTemplateFiles as file (file.id)}
                  <Select.Item value={file.id} label={file.name}>
                    {file.name}
                  </Select.Item>
                {/each}
              </Select.Group>
            </Select.Content>
          </Select.Root>
        </Field.Field>
      </Field.FieldGroup>
      <Input
        bind:ref={uploadInput}
        type="file"
        accept=".docx"
        class="hidden"
        aria-label={m.flow_template_fill_upload_action()}
        disabled={cannotEdit || busy}
        onchange={(event) => onTemplateUpload?.({ event })}
      />
      <div class="flex flex-wrap gap-2">
        <Button disabled={cannotEdit || busy} onclick={() => uploadInput?.click()}>
          {#if templateInspecting}<Spinner data-icon="inline-start" aria-hidden="true" />{/if}
          {m.flow_template_fill_upload_action()}
        </Button>
        {#if resolvedTemplateAssetId}
          <Button
            variant="outline"
            disabled={busy || selectedTemplateAsset?.can_download === false}
            onclick={() => onTemplateDownload?.()}
          >
            <IconDownload data-icon="inline-start" />
            {m.flow_template_fill_download_action()}
          </Button>
          <Button variant="outline" disabled={busy} onclick={() => onTemplateRefresh?.()}>
            {m.flow_template_fill_refresh_action()}
          </Button>
        {/if}
      </div>
      {#if busy}
        <p role="status" class="flex items-center gap-2">
          <Spinner aria-hidden="true" />
          {templateInspecting
            ? m.flow_template_fill_inspecting()
            : m.flow_template_fill_loading_templates()}
        </p>
      {/if}
      {#if selectedTemplateAsset}
        <div class="flex flex-wrap items-center gap-2">
          <Badge variant="outline"
            >{getTemplateAssetStatusLabel(selectedTemplateAsset.status)}</Badge
          >
          {#if selectedTemplateAsset.last_updated_by_name}
            <Field.FieldDescription
              >{m.flow_template_last_updated_by({
                name: selectedTemplateAsset.last_updated_by_name
              })}</Field.FieldDescription
            >
          {/if}
        </div>
      {/if}
      {#if templateConfigError}
        <Alert.Root variant="destructive">
          <Alert.Title>{m.flow_template_fill_error_title()}</Alert.Title>
          <Alert.Description class="flex flex-col gap-3">
            <p>{templateConfigError}</p>
            {#if templateCanRetry}
              <Button
                bind:ref={retryButton}
                variant="outline"
                class="self-start"
                disabled={busy}
                onclick={() => void retryTemplate()}
              >
                {m.flow_template_fill_retry_action()}
              </Button>
            {/if}
          </Alert.Description>
        </Alert.Root>
      {/if}
      <Alert.Root role="note">
        <Alert.Title>{m.flow_template_fill_word_help_title()}</Alert.Title>
        <Alert.Description class="flex flex-col gap-3">
          <p>{m.flow_template_fill_word_help_intro()}</p>
          <Collapsible.Root>
            <Collapsible.Trigger>
              {#snippet child({ props })}
                <Button {...props} variant="outline" size="sm"
                  >{m.flow_template_fill_word_help_open()}</Button
                >
              {/snippet}
            </Collapsible.Trigger>
            <Collapsible.Content class="pt-3">
              <ol class="flex list-decimal flex-col gap-2 pl-5">
                <li>{m.flow_template_fill_word_help_step_one()}</li>
                <li>{m.flow_template_fill_word_help_step_two()}</li>
                <li>{m.flow_template_fill_word_help_step_three()}</li>
                <li>{m.flow_template_fill_word_help_step_four()}</li>
              </ol>
              <p class="pt-3">{m.flow_template_fill_word_help_migration()}</p>
              <Alert.Root role="note" class="mt-3">
                <Alert.Title>{m.flow_template_fill_accessibility_title()}</Alert.Title>
                <Alert.Description>{m.flow_template_fill_accessibility_body()}</Alert.Description>
              </Alert.Root>
            </Collapsible.Content>
          </Collapsible.Root>
          <Button
            variant="link"
            class="self-start"
            href={asset("/examples/eneo-word-template.docx")}
            download="eneo-word-template.docx"
          >
            <IconDownload data-icon="inline-start" />
            {m.flow_template_fill_example_action()}
          </Button>
        </Alert.Description>
      </Alert.Root>
    </Card.Content>
    <Card.Footer class="flex flex-wrap items-center justify-between gap-3">
      <Badge variant="secondary">{m.flow_output_type_docx()}</Badge>
      <Button
        variant="outline"
        size="sm"
        disabled={isPublished || busy}
        onclick={() => onOutputModeChange?.({ value: "pass_through" })}
      >
        {m.flow_template_fill_switch_back()}
      </Button>
    </Card.Footer>
  </Card.Root>

  <Card.Root>
    <Card.Header>
      <Card.Title role="heading" aria-level={3}
        >{m.flow_template_fill_placeholders_title()}</Card.Title
      >
      <Card.Description>{m.flow_template_fill_mapping_help()}</Card.Description>
    </Card.Header>
    <Card.Content class="flex flex-col gap-4">
      {#if templateHasSelection && templateReadiness.total > 0}
        <div class="flex flex-wrap items-center justify-between gap-3" role="status">
          <Badge variant={templateReadiness.incomplete ? "outline" : "secondary"}>
            {m.flow_template_fill_readiness_summary({
              matched: String(templateReadiness.matched),
              total: String(templateReadiness.total)
            })}
          </Badge>
          {#if templateAutoMatchableCount > 0}
            <Button
              variant="outline"
              size="sm"
              disabled={isPublished || templateInspecting}
              onclick={() => onApplyAllSuggestions?.()}
            >
              {m.flow_template_fill_apply_all({ count: String(templateAutoMatchableCount) })}
            </Button>
          {/if}
        </div>
      {/if}
      {#if templateUnnamedStepWarning}
        <Alert.Root role="note"
          ><Alert.Description>{m.flow_template_fill_naming_hint()}</Alert.Description></Alert.Root
        >
      {/if}
      {#if templateOrphanedRows.length > 0}
        <Alert.Root variant="destructive">
          <Alert.Title
            >{m.flow_template_fill_orphaned_warning({
              count: String(templateOrphanedRows.length)
            })}</Alert.Title
          >
          <Alert.Description>{m.flow_template_fill_orphaned_row_warning()}</Alert.Description>
        </Alert.Root>
      {/if}
      {#if !templateHasSelection}
        <Empty.Root>
          <Empty.Header>
            <Empty.Title>{m.flow_template_fill_select_template_first_title()}</Empty.Title>
            <Empty.Description
              >{m.flow_template_fill_select_template_first_body()}</Empty.Description
            >
          </Empty.Header>
        </Empty.Root>
      {:else if templatePlaceholders.length === 0 && !templateInspecting}
        <Alert.Root variant="destructive">
          <Alert.Title>{m.flow_template_fill_no_placeholders()}</Alert.Title>
          <Alert.Description>{m.flow_template_fill_control_guidance()}</Alert.Description>
        </Alert.Root>
        {#if isAdvancedMode && templateInspection?.extracted_text_preview}
          <pre
            class="overflow-auto whitespace-pre-wrap">{templateInspection.extracted_text_preview}</pre>
        {/if}
      {:else}
        <Field.FieldGroup>
          {#each templateBindingRows as row, index (row.key)}
            <Card.Root>
              <Card.Header>
                <Card.Title role="heading" aria-level={4} class="break-words"
                  >{row.label}</Card.Title
                >
                {#if row.label !== row.placeholderName}
                  <Card.Description
                    >{m.flow_template_fill_word_tag({
                      name: row.placeholderName
                    })}</Card.Description
                  >
                {/if}
                {#if row.hint}<Card.Description>{row.hint}</Card.Description>{/if}
                <div class="flex flex-wrap gap-2">
                  {#if row.kind}
                    <Badge variant="outline"
                      >{row.kind === "rich"
                        ? m.flow_template_fill_kind_rich()
                        : m.flow_template_fill_kind_text()}</Badge
                    >
                  {/if}
                  <Badge variant={row.status === "orphaned" ? "destructive" : "secondary"}
                    >{getTemplateRowStatusText(row.status)}</Badge
                  >
                  {#if row.autoSuggested}<Badge variant="outline"
                      >{m.flow_template_fill_auto_badge()}</Badge
                    >{/if}
                </div>
              </Card.Header>
              <Card.Content class="flex flex-col gap-3">
                <Field.Field data-invalid={row.status === "orphaned"}>
                  <Field.FieldLabel for={`${instanceId}-source-${index}`}>
                    {m.flow_template_fill_binding_label({ name: row.label })}
                  </Field.FieldLabel>
                  <Select.Root
                    type="single"
                    value={row.binding ?? "__unset__"}
                    disabled={isPublished}
                    onValueChange={(value) =>
                      onBindingChange?.({ placeholder: row.placeholderName, value })}
                  >
                    <Select.Trigger
                      id={`${instanceId}-source-${index}`}
                      class="w-full"
                      aria-invalid={row.status === "orphaned"}
                    >
                      <span class="min-w-0 truncate">{bindingLabel(row.binding)}</span>
                    </Select.Trigger>
                    <Select.Content>
                      <Select.Group>
                        <Select.Item value="__unset__" label={m.flow_template_fill_select_source()}
                          >{m.flow_template_fill_select_source()}</Select.Item
                        >
                        <Select.Item value="" label={m.flow_template_fill_leave_empty()}
                          >{m.flow_template_fill_leave_empty()}</Select.Item
                        >
                      </Select.Group>
                      {#each templateBindingSuggestionGroups as group (group.key)}
                        <Select.Group>
                          <Select.GroupHeading>{group.label}</Select.GroupHeading>
                          {#each group.options as option (option.value)}
                            <Select.Item value={option.value} label={option.label}
                              >{option.label}</Select.Item
                            >
                          {/each}
                        </Select.Group>
                      {/each}
                    </Select.Content>
                  </Select.Root>
                  {#if row.kind}
                    <Field.FieldDescription
                      >{row.kind === "rich"
                        ? m.flow_template_fill_kind_help_rich()
                        : m.flow_template_fill_kind_help_text()}</Field.FieldDescription
                    >
                  {/if}
                  {#if row.status === "orphaned"}<Field.FieldError
                      >{m.flow_template_fill_orphaned_row_warning()}</Field.FieldError
                    >{/if}
                  {#if row.sourceOutputType === "json"}<Field.FieldError
                      >{m.flow_template_fill_json_warning()}</Field.FieldError
                    >{/if}
                </Field.Field>
                {#if row.status === "missing" && templateAutoBindings[row.placeholderName]}
                  <Button
                    variant="outline"
                    size="sm"
                    class="self-start"
                    disabled={isPublished}
                    onclick={() =>
                      onBindingChange?.({
                        placeholder: row.placeholderName,
                        value: templateAutoBindings[row.placeholderName]
                      })}
                  >
                    {m.flow_template_fill_apply_suggestion()}
                  </Button>
                {/if}
                {#if isAdvancedMode}
                  <Collapsible.Root>
                    <Collapsible.Trigger>
                      {#snippet child({ props })}
                        <Button {...props} variant="ghost" size="sm"
                          >{m.flow_template_fill_show_expression()}</Button
                        >
                      {/snippet}
                    </Collapsible.Trigger>
                    <Collapsible.Content class="pt-3">
                      <Field.Field>
                        <Field.FieldLabel for={`${instanceId}-expression-${index}`}
                          >{m.flow_template_fill_expression_label()}</Field.FieldLabel
                        >
                        <Input
                          id={`${instanceId}-expression-${index}`}
                          value={row.binding ?? ""}
                          disabled={isPublished}
                          placeholder={m.flow_template_fill_expression_placeholder({
                            expression: "{{step_1.output.text}}"
                          })}
                          oninput={(event) =>
                            onBindingChange?.({
                              placeholder: row.placeholderName,
                              value: event.currentTarget.value
                            })}
                        />
                      </Field.Field>
                    </Collapsible.Content>
                  </Collapsible.Root>
                {/if}
              </Card.Content>
            </Card.Root>
          {/each}
        </Field.FieldGroup>
      {/if}
      {#if templateHasSelection && templateReadiness.total > 0 && !templateReadiness.incomplete && templateOrphanedRows.length === 0}
        <Alert.Root role="status"
          ><Alert.Description>{m.flow_template_fill_ready_to_test()}</Alert.Description></Alert.Root
        >
      {/if}
    </Card.Content>
  </Card.Root>
</div>
