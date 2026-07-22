<script lang="ts">
  import { useId } from "bits-ui";
  import { ChevronDown, ChevronRight, CircleAlert } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { tick, untrack } from "svelte";
  import type { SkillFormValue, SkillRevisionFormValue } from "./skillBindings";

  type SharedProps = {
    submitLabel?: string;
    submittingLabel?: string;
    showDiscardAction?: boolean;
    onDirtyChange?: (dirty: boolean) => void;
  };

  type CreateProps = SharedProps & {
    mode?: "create";
    initialValue?: Partial<SkillFormValue>;
    onSubmit: (value: SkillFormValue) => Promise<void>;
  };

  type RevisionProps = SharedProps & {
    mode: "revision";
    initialValue?: Partial<SkillRevisionFormValue>;
    onSubmit: (value: SkillRevisionFormValue) => Promise<void>;
  };

  type Props = CreateProps | RevisionProps;

  let props: Props = $props();

  const id = useId();
  const displayNameId = `${id}-display-name`;
  const descriptionId = `${id}-description`;
  const instructionsId = `${id}-instructions`;
  const advancedId = `${id}-advanced`;
  const slugId = `${id}-slug`;

  const initialDisplayName = untrack(() => props.initialValue?.display_name ?? "");
  const initialDescription = untrack(() => props.initialValue?.description ?? "");
  const initialInstructions = untrack(() => props.initialValue?.instructions ?? "");
  const initialSlug = untrack(() =>
    props.mode === "revision"
      ? ""
      : (props.initialValue?.slug ?? deriveSkillSlug(initialDisplayName))
  );
  const initialSlugCustomized = untrack(
    () => props.mode !== "revision" && props.initialValue?.slug !== undefined
  );

  let displayName = $state(initialDisplayName);
  let description = $state(initialDescription);
  let instructions = $state(initialInstructions);
  let slug = $state(initialSlug);
  let slugCustomized = $state(initialSlugCustomized);
  let baseline = $state({
    displayName: initialDisplayName,
    description: initialDescription,
    instructions: initialInstructions,
    slug: initialSlug,
    slugCustomized: initialSlugCustomized
  });
  let advancedOpen = $state(false);
  let submitAttempted = $state(false);
  let isSubmitting = $state(false);
  let formError = $state<string | null>(null);
  let displayNameInput = $state<HTMLInputElement | null>(null);
  let descriptionInput = $state<HTMLTextAreaElement | null>(null);
  let instructionsInput = $state<HTMLTextAreaElement | null>(null);
  let slugInput = $state<HTMLInputElement | null>(null);

  const isCreateMode = $derived(props.mode !== "revision");
  const resolvedSubmitLabel = $derived(
    props.submitLabel ?? (isCreateMode ? m.skills_create_action() : m.save_changes())
  );
  const resolvedSubmittingLabel = $derived(
    props.submittingLabel ?? (isCreateMode ? m.skills_creating() : m.saving())
  );
  const displayNameInvalid = $derived(submitAttempted && displayName.trim().length === 0);
  const descriptionInvalid = $derived(submitAttempted && description.trim().length === 0);
  const instructionsInvalid = $derived(submitAttempted && instructions.trim().length === 0);
  const slugInvalid = $derived(isCreateMode && submitAttempted && slug.trim().length === 0);
  const hasInvalidField = $derived(
    displayNameInvalid || descriptionInvalid || instructionsInvalid || slugInvalid
  );
  const dirty = $derived(
    displayName !== baseline.displayName ||
      description !== baseline.description ||
      instructions !== baseline.instructions ||
      (isCreateMode && slug !== baseline.slug)
  );

  $effect(() => {
    props.onDirtyChange?.(dirty);
  });

  function handleDisplayNameInput(event: Event) {
    if (slugCustomized) return;
    slug = deriveSkillSlug((event.currentTarget as HTMLInputElement).value);
  }

  function handleSlugInput() {
    slugCustomized = true;
  }

  function discardChanges() {
    displayName = baseline.displayName;
    description = baseline.description;
    instructions = baseline.instructions;
    slug = baseline.slug;
    slugCustomized = baseline.slugCustomized;
    submitAttempted = false;
    formError = null;
  }

  async function revealInvalidSlug() {
    advancedOpen = true;
    await tick();
    slugInput?.focus();
  }

  async function focusFirstInvalidField() {
    if (displayNameInvalid || descriptionInvalid || instructionsInvalid) {
      await tick();
      if (displayNameInvalid) displayNameInput?.focus();
      else if (descriptionInvalid) descriptionInput?.focus();
      else instructionsInput?.focus();
      return;
    }
    if (slugInvalid) await revealInvalidSlug();
  }

  async function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    submitAttempted = true;
    formError = null;
    if (hasInvalidField) {
      await focusFirstInvalidField();
      return;
    }

    isSubmitting = true;
    try {
      const content: SkillRevisionFormValue = {
        display_name: displayName.trim(),
        description: description.trim(),
        instructions: instructions.trim()
      };
      const submittedSlug = slug.trim();
      if (props.mode === "revision") {
        await props.onSubmit(content);
      } else {
        await props.onSubmit({ ...content, slug: submittedSlug });
      }
      displayName = content.display_name;
      description = content.description;
      instructions = content.instructions;
      slug = submittedSlug;
      baseline = {
        displayName: content.display_name,
        description: content.description,
        instructions: content.instructions,
        slug: submittedSlug,
        slugCustomized
      };
      submitAttempted = false;
    } catch (error) {
      formError = getErrorMessage(error);
    } finally {
      isSubmitting = false;
    }
  }

  function deriveSkillSlug(value: string): string {
    return value
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 64)
      .replace(/-+$/g, "");
  }
</script>

<form class="flex flex-col gap-5" onsubmit={handleSubmit} aria-busy={isSubmitting} novalidate>
  <Field.Group>
    <Field.Field data-invalid={displayNameInvalid || undefined}>
      <Field.Label for={displayNameId}>{m.skills_display_name_label()}</Field.Label>
      <Input
        bind:ref={displayNameInput}
        id={displayNameId}
        bind:value={displayName}
        oninput={handleDisplayNameInput}
        aria-invalid={displayNameInvalid || undefined}
        aria-describedby={`${displayNameId}-description`}
        disabled={isSubmitting}
        maxlength={200}
        required
      />
      <Field.Description id={`${displayNameId}-description`}>
        {m.skills_display_name_description()}
      </Field.Description>
      {#if displayNameInvalid}
        <Field.Error>{m.skills_required_field()}</Field.Error>
      {/if}
    </Field.Field>

    <Field.Field data-invalid={descriptionInvalid || undefined}>
      <Field.Label for={descriptionId}>{m.skills_description_label()}</Field.Label>
      <Textarea
        bind:ref={descriptionInput}
        id={descriptionId}
        bind:value={description}
        aria-invalid={descriptionInvalid || undefined}
        aria-describedby={`${descriptionId}-description`}
        disabled={isSubmitting}
        rows={3}
        maxlength={1024}
        required
      />
      <Field.Description id={`${descriptionId}-description`}>
        {m.skills_description_description()}
      </Field.Description>
      {#if descriptionInvalid}
        <Field.Error>{m.skills_required_field()}</Field.Error>
      {/if}
    </Field.Field>

    <Field.Field data-invalid={instructionsInvalid || undefined}>
      <Field.Label for={instructionsId}>{m.skills_instructions_label()}</Field.Label>
      <Textarea
        bind:ref={instructionsInput}
        id={instructionsId}
        bind:value={instructions}
        aria-invalid={instructionsInvalid || undefined}
        aria-describedby={`${instructionsId}-description`}
        disabled={isSubmitting}
        class="max-h-[min(50dvh,32rem)] overflow-y-auto"
        rows={12}
        required
      />
      <Field.Description id={`${instructionsId}-description`}>
        {m.skills_instructions_description()}
      </Field.Description>
      {#if instructionsInvalid}
        <Field.Error>{m.skills_required_field()}</Field.Error>
      {/if}
    </Field.Field>
  </Field.Group>

  {#if isCreateMode}
    <div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        aria-expanded={advancedOpen}
        aria-controls={advancedId}
        onclick={() => (advancedOpen = !advancedOpen)}
      >
        {#if advancedOpen}
          <ChevronDown data-icon="inline-start" aria-hidden="true" />
        {:else}
          <ChevronRight data-icon="inline-start" aria-hidden="true" />
        {/if}
        {m.skills_advanced_options()}
      </Button>
    </div>

    {#if advancedOpen}
      <div id={advancedId}>
        <Field.Field data-invalid={slugInvalid || undefined}>
          <Field.Label for={slugId}>{m.skills_slug_label()}</Field.Label>
          <Input
            bind:ref={slugInput}
            id={slugId}
            bind:value={slug}
            oninput={handleSlugInput}
            aria-invalid={slugInvalid || undefined}
            aria-describedby={`${slugId}-description`}
            disabled={isSubmitting}
            autocomplete="off"
            maxlength={64}
            required
          />
          <Field.Description id={`${slugId}-description`}>
            {m.skills_slug_description()}
          </Field.Description>
          {#if slugInvalid}
            <Field.Error>{m.skills_required_field()}</Field.Error>
          {/if}
        </Field.Field>
      </div>
    {/if}
  {/if}

  {#if formError}
    <Alert.Root variant="destructive">
      <CircleAlert aria-hidden="true" />
      <Alert.Title>
        {isCreateMode ? m.skills_form_error_title() : m.skills_revision_form_error_title()}
      </Alert.Title>
      <Alert.Description>{formError}</Alert.Description>
    </Alert.Root>
  {/if}

  <div class="flex justify-end gap-2">
    {#if props.showDiscardAction && dirty}
      <Button type="button" variant="destructive" disabled={isSubmitting} onclick={discardChanges}>
        {m.discard_all_changes()}
      </Button>
    {/if}
    <Button type="submit" disabled={isSubmitting} aria-busy={isSubmitting}>
      {isSubmitting ? resolvedSubmittingLabel : resolvedSubmitLabel}
    </Button>
  </div>
</form>
