<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { ChevronDown, ChevronRight } from "lucide-svelte";

  type WizardSection = {
    required?: boolean;
    title?: string;
    description?: string;
  } | null;

  let {
    wizard = $bindable({
      attachments: null,
      collections: null
    })
  }: {
    wizard: {
      attachments: WizardSection;
      collections: WizardSection;
    };
  } = $props();

  // Track if each section is enabled
  let attachmentsEnabled = $state(wizard.attachments !== null);
  let collectionsEnabled = $state(wizard.collections !== null);

  // Track if sections are expanded (for UI)
  let attachmentsExpanded = $state(true);
  let collectionsExpanded = $state(true);

  // Local state for form fields
  let attachmentsRequired = $state(wizard.attachments?.required ?? false);
  let attachmentsTitle = $state(wizard.attachments?.title ?? "");
  let attachmentsDescription = $state(wizard.attachments?.description ?? "");

  let collectionsRequired = $state(wizard.collections?.required ?? false);
  let collectionsTitle = $state(wizard.collections?.title ?? "");
  let collectionsDescription = $state(wizard.collections?.description ?? "");

  // Update wizard object when attachments settings change
  $effect(() => {
    if (attachmentsEnabled) {
      wizard.attachments = {
        required: attachmentsRequired,
        title: attachmentsTitle || undefined,
        description: attachmentsDescription || undefined
      };
    } else {
      wizard.attachments = null;
    }
  });

  // Update wizard object when collections settings change
  $effect(() => {
    if (collectionsEnabled) {
      wizard.collections = {
        required: collectionsRequired,
        title: collectionsTitle || undefined,
        description: collectionsDescription || undefined
      };
    } else {
      wizard.collections = null;
    }
  });

  // Initialize local state from wizard prop
  $effect(() => {
    if (wizard.attachments) {
      attachmentsEnabled = true;
      attachmentsRequired = wizard.attachments.required ?? false;
      attachmentsTitle = wizard.attachments.title ?? "";
      attachmentsDescription = wizard.attachments.description ?? "";
    }
    if (wizard.collections) {
      collectionsEnabled = true;
      collectionsRequired = wizard.collections.required ?? false;
      collectionsTitle = wizard.collections.title ?? "";
      collectionsDescription = wizard.collections.description ?? "";
    }
  });
</script>

<div class="flex flex-col gap-4">
  <div class="flex flex-col gap-1">
    <h3 class="text-default text-lg font-semibold">{m.wizard_configuration()}</h3>
    <p class="text-dimmer text-sm">{m.wizard_configuration_description()}</p>
  </div>

  <!-- Attachments Section -->
  <div class="border-default rounded-lg border">
    <div class="flex items-center justify-between p-4">
      <div class="flex items-center gap-3">
        <button
          type="button"
          onclick={() => (attachmentsExpanded = !attachmentsExpanded)}
          class="text-dimmer hover:text-default transition-colors"
          aria-label={attachmentsExpanded ? m.aria_collapse() : m.aria_expand()}
        >
          {#if attachmentsExpanded}
            <ChevronDown size={20} />
          {:else}
            <ChevronRight size={20} />
          {/if}
        </button>
        <div class="flex flex-col gap-0.5">
          <span class="text-default font-medium">{m.wizard_attachments_section()}</span>
          <span class="text-dimmer text-sm">{m.wizard_attachments_description()}</span>
        </div>
      </div>
      <Input.Switch bind:value={attachmentsEnabled} aria-label={m.enable_attachments()} />
    </div>

    {#if attachmentsEnabled && attachmentsExpanded}
      <div class="border-default flex flex-col gap-3 border-t p-4">
        <Input.Switch
          bind:value={attachmentsRequired}
          label={m.required()}
          description={m.wizard_attachments_required_description()}
        />
        <Input.Text
          bind:value={attachmentsTitle}
          label={m.custom_title()}
          placeholder={m.wizard_attachments_title_placeholder()}
        />
        <Input.TextArea
          bind:value={attachmentsDescription}
          label={m.custom_description()}
          placeholder={m.wizard_attachments_description_placeholder()}
          rows={2}
        />
      </div>
    {/if}
  </div>

  <!-- Collections Section -->
  <div class="border-default rounded-lg border">
    <div class="flex items-center justify-between p-4">
      <div class="flex items-center gap-3">
        <button
          type="button"
          onclick={() => (collectionsExpanded = !collectionsExpanded)}
          class="text-dimmer hover:text-default transition-colors"
          aria-label={collectionsExpanded ? m.aria_collapse() : m.aria_expand()}
        >
          {#if collectionsExpanded}
            <ChevronDown size={20} />
          {:else}
            <ChevronRight size={20} />
          {/if}
        </button>
        <div class="flex flex-col gap-0.5">
          <span class="text-default font-medium">{m.wizard_collections_section()}</span>
          <span class="text-dimmer text-sm">{m.wizard_collections_description()}</span>
        </div>
      </div>
      <Input.Switch bind:value={collectionsEnabled} aria-label={m.enable_collections()} />
    </div>

    {#if collectionsEnabled && collectionsExpanded}
      <div class="border-default flex flex-col gap-3 border-t p-4">
        <Input.Switch
          bind:value={collectionsRequired}
          label={m.required()}
          description={m.wizard_collections_required_description()}
        />
        <Input.Text
          bind:value={collectionsTitle}
          label={m.custom_title()}
          placeholder={m.wizard_collections_title_placeholder()}
        />
        <Input.TextArea
          bind:value={collectionsDescription}
          label={m.custom_description()}
          placeholder={m.wizard_collections_description_placeholder()}
          rows={2}
        />
      </div>
    {/if}
  </div>
</div>
