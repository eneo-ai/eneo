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
  import { Separator } from "$lib/components/ui/separator/index.js";
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
    onApplyAllSuggestions,
    onRemoveOrphanedBindings
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
    onRemoveOrphanedBindings?: () => void;
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
  const currentTemplateRows = $derived(
    templateBindingRows.filter((row) => row.status !== "orphaned")
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

  function focusTemplateField(index: number) {
    const target = document.getElementById(
      `${instanceId}-${isPublished ? "field" : "source"}-${index}`
    );
    target?.focus({ preventScroll: true });
    target?.scrollIntoView({ block: "center" });
  }

  async function removeOrphanedBindings() {
    const originKey = stepKey;
    onRemoveOrphanedBindings?.();
    await tick();
    if (stepKey !== originKey) return;
    if (currentTemplateRows.length > 0) focusTemplateField(0);
    else templateTrigger?.focus();
  }
</script>

<div class="flex flex-col gap-6">
  <Card.Root>
    <Card.Header>
      <Card.Title role="heading" aria-level={3}
        >{m.flow_template_fill_template_section()}</Card.Title
      >
      <Card.Description class="max-w-prose">{m.flow_template_fill_desc()}</Card.Description>
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
            <Select.Trigger
              bind:ref={templateTrigger}
              id={`${instanceId}-template`}
              class="min-h-8 w-full text-left data-[size=default]:h-auto"
            >
              <span class="min-w-0 break-words whitespace-normal">{templateAssetLabel}</span>
            </Select.Trigger>
            <Select.Content
              class="flex max-h-(--bits-select-content-available-height) w-(--bits-select-anchor-width) flex-col [&_[data-select-viewport]]:h-auto [&_[data-select-viewport]]:min-h-0"
            >
              <Select.Group>
                <Select.Item value="" label={m.flow_template_fill_select_placeholder()}>
                  {m.flow_template_fill_select_placeholder()}
                </Select.Item>
                {#each availableTemplateFiles as file (file.id)}
                  <Select.Item value={file.id} label={file.name}>
                    <span class="min-w-0 break-words whitespace-normal">{file.name}</span>
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
      {#if selectedTemplateAsset && !busy}
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
      <Separator />
      <Collapsible.Root class="flex flex-col gap-3">
        {#if !templateHasSelection}
          <p class="max-w-prose text-sm leading-relaxed">
            {m.flow_template_fill_word_help_intro()}
          </p>
        {/if}
        <div class="flex flex-wrap items-center gap-2">
          <Collapsible.Trigger>
            {#snippet child({ props })}
              <Button {...props} variant="outline" size="sm">
                {m.flow_template_fill_word_help_open()}
              </Button>
            {/snippet}
          </Collapsible.Trigger>
          <Button
            variant="link"
            size="sm"
            href={asset("/examples/eneo-word-template.docx")}
            download="eneo-word-template.docx"
          >
            <IconDownload data-icon="inline-start" />
            {m.flow_template_fill_example_action()}
          </Button>
          <Button
            variant="link"
            size="sm"
            href={asset("/examples/eneo-word-template-fields.docx")}
            download="eneo-word-template-fields.docx"
          >
            <IconDownload data-icon="inline-start" />
            {m.flow_template_fill_fields_example_action()}
          </Button>
        </div>
        <Collapsible.Content class="flex max-w-prose flex-col gap-4 pt-4 text-sm leading-relaxed">
          <p>{m.flow_template_fill_example_help()}</p>
          <p>{m.flow_template_fill_fields_example_help()}</p>
          <div class="flex flex-col gap-2">
            <p class="font-medium">{m.flow_template_fill_word_help_windows_title()}</p>
            <ol class="flex list-decimal flex-col gap-2 pl-5">
              <li>{m.flow_template_fill_word_help_step_one()}</li>
              <li>{m.flow_template_fill_word_help_step_two()}</li>
              <li>{m.flow_template_fill_word_help_step_three()}</li>
              <li>{m.flow_template_fill_word_help_step_four()}</li>
            </ol>
            <p>{m.flow_template_fill_word_control_appearance_help()}</p>
          </div>
          <div class="flex flex-col gap-2">
            <p class="font-medium">{m.flow_template_fill_word_help_mac_title()}</p>
            <p>{m.flow_template_fill_word_help_mac_tab()}</p>
            <p>{m.flow_template_fill_word_help_mac_controls()}</p>
          </div>
          <p>{m.flow_template_fill_word_help_migration()}</p>
          <div class="flex flex-col items-start gap-2">
            <Button
              variant="link"
              class="h-auto text-left whitespace-normal"
              href="https://support.microsoft.com/en-gb/word/show-the-developer-tab-in-word"
              target="_blank"
              rel="noopener noreferrer">{m.flow_template_fill_word_help_tab_link()}</Button
            >
            <Button
              variant="link"
              class="h-auto text-left whitespace-normal"
              href="https://support.microsoft.com/en-us/word/create-a-form-in-word-that-users-can-complete-or-print"
              target="_blank"
              rel="noopener noreferrer">{m.flow_template_fill_word_help_controls_link()}</Button
            >
          </div>
          <Alert.Root role="note">
            <Alert.Title>{m.flow_template_fill_accessibility_title()}</Alert.Title>
            <Alert.Description>{m.flow_template_fill_accessibility_body()}</Alert.Description>
          </Alert.Root>
        </Collapsible.Content>
      </Collapsible.Root>
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
      <Card.Description class="max-w-prose">{m.flow_template_fill_mapping_help()}</Card.Description>
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
          <Alert.Description class="flex flex-col gap-3">
            <p class="max-w-prose">{m.flow_template_fill_orphaned_help()}</p>
            <ul class="list-disc pl-5">
              {#each templateOrphanedRows as row (row.key)}
                <li class="break-words">{row.label}</li>
              {/each}
            </ul>
            <Button
              variant="outline"
              class="self-start"
              disabled={isPublished || busy}
              onclick={() => void removeOrphanedBindings()}
            >
              {m.flow_template_fill_remove_orphaned()}
            </Button>
          </Alert.Description>
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
        {#if templateInspection && !busy && templatePlaceholders.length > 1}
          <Collapsible.Root class="flex flex-col gap-3">
            <Collapsible.Trigger>
              {#snippet child({ props })}
                <Button {...props} variant="outline" size="sm" class="self-start">
                  {m.flow_template_fill_locations_action()}
                </Button>
              {/snippet}
            </Collapsible.Trigger>
            <Collapsible.Content class="flex flex-col gap-3">
              <p class="text-muted-foreground max-w-prose text-sm leading-relaxed">
                {m.flow_template_fill_locations_help()}
              </p>
              <ol class="flex max-w-prose list-decimal flex-col gap-1 pl-5 text-sm">
                {#each currentTemplateRows as row, index (row.key)}
                  <li>
                    <Button
                      variant="ghost"
                      class="h-auto w-full items-start justify-between gap-3 py-3 text-left whitespace-normal"
                      aria-label={m.flow_template_fill_go_to_field({ name: row.label })}
                      aria-describedby={row.status !== "matched"
                        ? `${instanceId}-location-status-${index}`
                        : undefined}
                      onclick={() => focusTemplateField(index)}
                    >
                      <span class="flex min-w-0 flex-col gap-1 break-words">
                        <span class="font-medium">{row.label}</span>
                        <span class="text-muted-foreground font-normal">
                          {row.sectionHeading
                            ? m.flow_template_fill_under_heading({ heading: row.sectionHeading })
                            : m.flow_template_fill_in_body()}
                        </span>
                      </span>
                      {#if row.status !== "matched"}
                        <Badge
                          id={`${instanceId}-location-status-${index}`}
                          variant={row.status === "invalid" ? "secondary" : "outline"}
                          class={row.status === "invalid"
                            ? "bg-negative-dimmer text-negative-stronger"
                            : undefined}
                        >
                          {getTemplateRowStatusText(row.status)}
                        </Badge>
                      {/if}
                    </Button>
                  </li>
                {/each}
              </ol>
            </Collapsible.Content>
          </Collapsible.Root>
          <Separator />
        {/if}
        <Field.FieldGroup>
          {#each currentTemplateRows as row, index (row.key)}
            {#if index > 0}<Separator />{/if}
            <Field.FieldSet id={`${instanceId}-field-${index}`} tabindex={-1} class="min-w-0">
              <Field.FieldLegend>{row.label}</Field.FieldLegend>
              {#if row.sectionHeading}
                <Field.FieldDescription class="text-foreground">
                  {m.flow_template_fill_under_heading({ heading: row.sectionHeading })}
                </Field.FieldDescription>
              {/if}
              <div class="flex flex-wrap items-center gap-2">
                {#if row.label !== row.placeholderName}
                  <Field.FieldDescription
                    >{m.flow_template_fill_word_tag({
                      name: row.placeholderName
                    })}</Field.FieldDescription
                  >
                {/if}
                {#if row.kind}
                  <Badge variant="outline"
                    >{row.kind === "rich"
                      ? m.flow_template_fill_kind_rich()
                      : m.flow_template_fill_kind_text()}</Badge
                  >
                {/if}
                <Badge
                  variant="secondary"
                  class={row.status === "invalid"
                    ? "bg-negative-dimmer text-negative-stronger"
                    : undefined}>{getTemplateRowStatusText(row.status)}</Badge
                >
                {#if row.autoSuggested}<Badge variant="outline"
                    >{m.flow_template_fill_auto_badge()}</Badge
                  >{/if}
              </div>
              <Field.Field
                data-invalid={row.status === "invalid"}
                class="data-[invalid=true]:text-negative-stronger"
              >
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
                    class="min-h-8 w-full text-left data-[size=default]:h-auto"
                    aria-invalid={row.status === "invalid"}
                    aria-describedby={row.sourceOutputType === "json"
                      ? `${instanceId}-binding-error-${index}`
                      : undefined}
                  >
                    <span class="min-w-0 break-words whitespace-normal"
                      >{bindingLabel(row.binding)}</span
                    >
                  </Select.Trigger>
                  <Select.Content
                    class="flex max-h-(--bits-select-content-available-height) w-(--bits-select-anchor-width) flex-col [&_[data-select-viewport]]:h-auto [&_[data-select-viewport]]:min-h-0"
                  >
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
                            ><span class="min-w-0 break-words whitespace-normal"
                              >{option.label}</span
                            ></Select.Item
                          >
                        {/each}
                      </Select.Group>
                    {/each}
                  </Select.Content>
                </Select.Root>
                {#if row.kind}
                  <Field.FieldDescription class="max-w-prose"
                    >{row.kind === "rich"
                      ? m.flow_template_fill_kind_help_rich()
                      : m.flow_template_fill_kind_help_text()}</Field.FieldDescription
                  >
                {/if}
                {#if row.kind === "rich" && templateBindingSuggestionGroups.some((group) => group.key === "form" && group.options.some((option) => option.value === row.binding))}
                  <Field.FieldDescription class="text-foreground"
                    >{m.flow_template_fill_form_source_help()}</Field.FieldDescription
                  >
                {/if}
                {#if row.sourceOutputType === "json"}<Field.FieldError
                    id={`${instanceId}-binding-error-${index}`}
                    class="text-negative-stronger"
                    >{m.flow_template_fill_json_warning()}</Field.FieldError
                  >{/if}
              </Field.Field>
              {#if row.hint}
                <Collapsible.Root>
                  <Collapsible.Trigger>
                    {#snippet child({ props })}
                      <Button {...props} variant="outline" size="sm"
                        >{m.flow_template_fill_example_text_action()}</Button
                      >
                    {/snippet}
                  </Collapsible.Trigger>
                  <Collapsible.Content class="pt-3">
                    <p id={`${instanceId}-preview-label-${index}`} class="mb-2 text-sm font-medium">
                      {m.flow_template_fill_template_text_label()}
                    </p>
                    <Field.FieldDescription
                      class="bg-muted text-foreground max-h-64 max-w-prose overflow-auto rounded-md p-4 leading-relaxed break-words whitespace-pre-wrap"
                      role="region"
                      tabindex={0}
                      aria-labelledby={`${instanceId}-preview-label-${index}`}
                      >{row.hint}</Field.FieldDescription
                    >
                  </Collapsible.Content>
                </Collapsible.Root>
              {/if}
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
            </Field.FieldSet>
          {/each}
        </Field.FieldGroup>
      {/if}
      {#if templateHasSelection && !busy && !templateConfigError && templateReadiness.total > 0 && !templateReadiness.incomplete && templateOrphanedRows.length === 0}
        <Alert.Root role="status"
          ><Alert.Description class="max-w-prose"
            >{m.flow_template_fill_ready_to_test()}</Alert.Description
          ></Alert.Root
        >
      {/if}
    </Card.Content>
  </Card.Root>
</div>
