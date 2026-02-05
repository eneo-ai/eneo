<script lang="ts">
  import { onMount } from "svelte";
  import type {
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyType,
    Space,
    Assistant
  } from "@intric/intric-js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import {
    Key,
    Shield,
    Settings2,
    ChevronRight,
    ChevronLeft,
    Check,
    AlertCircle,
    Globe,
    Lock,
    Building2,
    MessageSquare,
    AppWindow,
    Info,
    Eye,
    Pencil,
    ShieldCheck,
    Sparkles
  } from "lucide-svelte";
  import { fly, fade } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import ScopeResourceSelector from "./ScopeResourceSelector.svelte";
  import TagInput from "./TagInput.svelte";
  import ExpirationPicker from "./ExpirationPicker.svelte";

  const intric = getIntric();

  let { onCreated }: { onCreated: (response: ApiKeyCreatedResponse) => void } = $props();

  let showDialog = $state<Dialog.OpenState>(undefined);
  let isSubmitting = $state(false);
  let errorMessage = $state<string | null>(null);

  // Wizard step state
  let currentStep = $state(1);
  const totalSteps = 3;
  let stepDirection = $state<"forward" | "backward">("forward");

  // Step 1: Basic info
  let name = $state("");
  let description = $state("");
  let keyType = $state<ApiKeyType>("sk_");

  // Step 2: Scope & permissions
  let permission = $state<ApiKeyPermission>("read");
  let scopeType = $state<ApiKeyScopeType>("tenant");
  let scopeId = $state<string | null>(null);
  let manualScopeId = $state("");

  // Fine-grained permissions (HuggingFace-style)
  type ResourcePermission = "none" | "read" | "write" | "admin";

  // Per-resource permission levels
  let assistantsPermission = $state<ResourcePermission>("none");
  let appsPermission = $state<ResourcePermission>("none");
  let spacesPermission = $state<ResourcePermission>("none");
  let knowledgePermission = $state<ResourcePermission>("none");

  // Permission mode
  let permissionMode = $state<"simple" | "fine-grained">("simple");

  // Step 3: Security settings
  let allowedOrigins = $state<string[]>([]);
  let allowedIps = $state<string[]>([]);
  let expiresAt = $state<string | null>(null);
  let rateLimit = $state("");

  // Resources for scope selection
  let spaces = $state<Space[]>([]);
  let assistants = $state<Assistant[]>([]);
  let appOptions = $state<{ id: string; name: string; spaceName?: string }[]>([]);
  let loadingResources = $state(false);

  // Step definitions - using a getter function to access translations
  const getSteps = () => [
    { number: 1, title: m.api_keys_step_basic_info(), icon: Key, subtitle: m.api_keys_step_basic_subtitle() },
    { number: 2, title: m.api_keys_step_scope(), icon: Shield, subtitle: m.api_keys_step_scope_subtitle() },
    { number: 3, title: m.api_keys_step_security(), icon: Settings2, subtitle: m.api_keys_step_security_subtitle() }
  ];
  const steps = $derived(getSteps());

  // Transition config
  const transitionDuration = 250;
  const flyX = $derived(stepDirection === "forward" ? 30 : -30);

  // Count active fine-grained permissions
  const activeResourceCount = $derived(
    [assistantsPermission, appsPermission, spacesPermission, knowledgePermission]
      .filter(p => p !== "none").length
  );

  // Effect: Reset permission to read for public keys
  $effect(() => {
    if (keyType === "pk_" && permission !== "read") {
      permission = "read";
      permissionMode = "simple";
    }
  });

  // Effect: Reset scope ID when scope type changes
  $effect(() => {
    if (scopeType) {
      scopeId = null;
      manualScopeId = "";
    }
  });

  // Effect: Use manual scope ID if provided
  $effect(() => {
    if (manualScopeId.trim()) {
      scopeId = manualScopeId.trim();
    }
  });

  // Effect: Scroll content area to top when step changes
  $effect(() => {
    if (currentStep) {
      const scrollArea = document.querySelector('.step-content-scroll');
      if (scrollArea) {
        scrollArea.scrollTop = 0;
      }
    }
  });

  async function loadResources() {
    loadingResources = true;
    try {
      spaces = await intric.spaces.list();
      assistants = await intric.assistants.list();
      const appLists = await Promise.all(
        spaces.map(async (space) => {
          const apps = await intric.spaces.listApplications({ id: space.id });
          return (apps?.items ?? []).map((app: { id: string; name: string }) => ({
            id: app.id,
            name: app.name,
            spaceName: space.name
          }));
        })
      );
      appOptions = appLists.flat();
    } catch (error) {
      console.error(error);
    } finally {
      loadingResources = false;
    }
  }

  onMount(() => {
    void loadResources();
  });

  function validateStep(step: number): string | null {
    switch (step) {
      case 1:
        if (!name.trim()) return m.api_keys_name_required();
        return null;
      case 2:
        if (permissionMode === "simple" && scopeType !== "tenant" && !scopeId && !manualScopeId.trim()) {
          return m.api_keys_select_scope({ scopeType });
        }
        return null;
      case 3:
        if (keyType === "pk_" && allowedOrigins.length === 0) {
          return m.api_keys_origin_required();
        }
        return null;
      default:
        return null;
    }
  }

  function isStepComplete(step: number): boolean {
    return validateStep(step) === null;
  }

  function nextStep() {
    const error = validateStep(currentStep);
    if (error) {
      errorMessage = error;
      return;
    }
    errorMessage = null;
    stepDirection = "forward";
    if (currentStep < totalSteps) {
      currentStep++;
    }
  }

  function prevStep() {
    errorMessage = null;
    stepDirection = "backward";
    if (currentStep > 1) {
      currentStep--;
    }
  }

  function goToStep(step: number) {
    if (step <= currentStep || (step === currentStep + 1 && isStepComplete(currentStep))) {
      errorMessage = null;
      stepDirection = step > currentStep ? "forward" : "backward";
      currentStep = step;
    }
  }

  async function createKey() {
    for (let i = 1; i <= totalSteps; i++) {
      const error = validateStep(i);
      if (error) {
        errorMessage = error;
        currentStep = i;
        return;
      }
    }

    errorMessage = null;
    isSubmitting = true;

    const request: ApiKeyCreateRequest = {
      name: name.trim(),
      description: description.trim() || null,
      key_type: keyType,
      permission,
      scope_type: scopeType,
      scope_id: scopeType === "tenant" ? null : (scopeId || manualScopeId.trim() || null),
      allowed_origins: keyType === "pk_" && allowedOrigins.length > 0 ? allowedOrigins : null,
      allowed_ips: keyType === "sk_" && allowedIps.length > 0 ? allowedIps : null,
      expires_at: expiresAt,
      rate_limit: rateLimit ? Number(rateLimit) : null
    };

    try {
      const response = await intric.apiKeys.create(request);
      onCreated(response);
      showDialog = false;
      resetForm();
    } catch (error: unknown) {
      console.error(error);
      const err = error as { getReadableMessage?: () => string };
      errorMessage = err?.getReadableMessage?.() ?? m.something_went_wrong();
    } finally {
      isSubmitting = false;
    }
  }

  function resetForm() {
    currentStep = 1;
    stepDirection = "forward";
    name = "";
    description = "";
    keyType = "sk_";
    permission = "read";
    permissionMode = "simple";
    assistantsPermission = "none";
    appsPermission = "none";
    spacesPermission = "none";
    knowledgePermission = "none";
    scopeType = "tenant";
    scopeId = null;
    manualScopeId = "";
    allowedOrigins = [];
    allowedIps = [];
    expiresAt = null;
    rateLimit = "";
    errorMessage = null;
  }

  function handleOpenChange(open: boolean) {
    if (!open) {
      resetForm();
    }
  }

  // Quick action to set all fine-grained permissions
  function setAllPermissions(level: ResourcePermission) {
    assistantsPermission = level;
    appsPermission = level;
    spacesPermission = level;
    knowledgePermission = level;
  }

  // Permission level display config using Tailwind classes for dark mode support
  function getLevelClasses(level: ResourcePermission, isSelected: boolean): string {
    if (!isSelected) return "border-default bg-primary text-muted hover:border-dimmer hover:bg-subtle";
    switch (level) {
      case "none": return "border-stronger bg-subtle text-default";
      case "read": return "border-accent-default bg-accent-default/10 text-accent-default";
      case "write": return "border-purple-500 bg-purple-500/10 text-purple-600 dark:text-purple-400";
      case "admin": return "border-red-500 bg-red-500/10 text-red-600 dark:text-red-400";
    }
  }

  function getLevelBadgeClasses(level: ResourcePermission): string {
    switch (level) {
      case "none": return "bg-subtle text-default";
      case "read": return "bg-accent-default/15 text-accent-default";
      case "write": return "bg-purple-500/15 text-purple-600 dark:text-purple-400";
      case "admin": return "bg-red-500/15 text-red-600 dark:text-red-400";
    }
  }

  function getLevelLabel(level: ResourcePermission) {
    switch (level) {
      case "none": return m.api_keys_permission_no_access();
      case "read": return m.api_keys_permission_read();
      case "write": return m.api_keys_permission_write();
      case "admin": return m.api_keys_permission_admin();
    }
  }
</script>

<Dialog.Root bind:isOpen={showDialog} on:openChange={handleOpenChange}>
  <Dialog.Trigger asFragment let:trigger>
    <Button is={trigger} variant="primary" class="gap-2">
      <Key class="h-4 w-4" />
      {m.generate_api_key()}
    </Button>
  </Dialog.Trigger>

  <Dialog.Content width="large" class="!p-0 overflow-hidden !bg-primary max-h-[90vh] flex flex-col !rounded-2xl">
    <!-- Header with subtle gradient -->
    <div class="flex-shrink-0 px-6 pt-6 pb-5 bg-gradient-to-b from-subtle to-primary rounded-t-2xl">
      <Dialog.Title class="text-2xl font-bold tracking-tight text-default">
        {m.generate_new_api_key_title()}
      </Dialog.Title>
      <Dialog.Description class="mt-2 text-sm leading-relaxed max-w-xl text-secondary">
        {@html m.generate_api_key_warning()}
      </Dialog.Description>

      <!-- Step indicator - improved contrast and accessibility (WCAG 2.2 AA) -->
      <nav class="mt-6 hidden sm:flex items-center justify-between" aria-label="API key creation progress">
        <ol class="flex items-center justify-between w-full" role="list">
          {#each steps as step, index}
            {@const isActive = currentStep === step.number}
            {@const isCompleted = currentStep > step.number}
            {@const canNavigate = step.number <= currentStep || (step.number === currentStep + 1 && isStepComplete(currentStep))}
            {@const StepIcon = step.icon}

            <li class="flex items-center {index < steps.length - 1 ? 'flex-1' : ''}">
              <button
                type="button"
                onclick={() => goToStep(step.number)}
                disabled={!canNavigate}
                aria-label="Step {step.number}: {step.title}"
                aria-current={isActive ? "step" : undefined}
                class="group flex items-center gap-3 rounded-xl px-4 py-3 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:ring-offset-2
                  {isActive ? 'bg-accent-default/10' : ''}
                  {canNavigate ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'}"
              >
                <div
                  class="relative flex h-10 w-10 items-center justify-center rounded-full border-2 transition-all duration-200
                    {isActive ? 'border-accent-default bg-accent-default text-on-fill shadow-lg shadow-accent-default/40 step-bounce' : ''}
                    {isCompleted ? 'border-positive bg-positive/10 text-positive' : ''}
                    {!isActive && !isCompleted ? 'border-dimmer bg-primary text-secondary' : ''}"
                  aria-hidden="true"
                >
                  {#if isCompleted}
                    <Check class="h-5 w-5" strokeWidth={2.5} />
                  {:else}
                    <StepIcon class="h-5 w-5" />
                  {/if}
                </div>

                <!-- Desktop: Full label -->
                <div class="text-left">
                  <p
                    class="text-sm font-semibold
                      {isActive ? 'text-accent-default' : ''}
                      {isCompleted ? 'text-positive' : ''}
                      {!isActive && !isCompleted ? 'text-default' : ''}"
                  >
                    {step.title}
                  </p>
                  <p class="text-xs text-secondary">{step.subtitle}</p>
                </div>
              </button>

              {#if index < steps.length - 1}
                <div class="flex-1 mx-3" aria-hidden="true">
                  <div
                    class="h-1 w-full rounded-full transition-all duration-300
                      {isCompleted ? 'bg-positive' : 'bg-tertiary'}"
                  ></div>
                </div>
              {/if}
            </li>
          {/each}
        </ol>
      </nav>

      <!-- Mobile step dots -->
      <div class="flex justify-center gap-2 mt-4 sm:hidden">
        {#each steps as step}
          {@const isActive = currentStep === step.number}
          {@const isCompleted = currentStep > step.number}
          <button
            type="button"
            onclick={() => goToStep(step.number)}
            disabled={step.number > currentStep + 1}
            class="h-2.5 w-2.5 rounded-full transition-all duration-200
              {isActive ? 'bg-accent-default scale-125' : ''}
              {isCompleted ? 'bg-positive' : ''}
              {!isActive && !isCompleted ? 'bg-tertiary' : ''}
              disabled:opacity-40"
            aria-label="Step {step.number}"
          ></button>
        {/each}
      </div>
      <p class="text-center text-sm font-medium text-default mt-2 sm:hidden">
        {steps[currentStep - 1].title}
      </p>
    </div>

    <!-- Error message - sticky outside scrollable area -->
    {#if errorMessage}
      <div
        role="alert"
        aria-live="assertive"
        class="flex-shrink-0 mx-6 mt-4 mb-3 flex items-center gap-3 rounded-xl border border-negative-default/30 bg-negative-dimmer px-4 py-3"
        transition:fly={{ y: -8, duration: 180, easing: cubicOut }}
      >
        <div class="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-negative-default/15">
          <AlertCircle class="h-4 w-4 text-negative-default" aria-hidden="true" />
        </div>
        <p class="text-sm font-medium text-negative-default">{errorMessage}</p>
      </div>
    {/if}

    <!-- Step content - scrollable area with aria-live for screen reader announcements -->
    <div class="step-content-scroll flex-1 min-h-0 overflow-y-auto scroll-smooth px-6 pt-4 pb-5" aria-live="polite" aria-atomic="false">
      <div class="grid items-start py-2" style="grid-template: 1fr / 1fr;">
        {#key currentStep}
          <div
            in:fly={{ x: flyX, duration: transitionDuration, delay: transitionDuration * 0.4, easing: cubicOut }}
            out:fade={{ duration: transitionDuration * 0.35 }}
            class="w-full"
            style="grid-area: 1 / 1; will-change: transform, opacity;"
          >
            {#if currentStep === 1}
              <!-- Step 1: Basic Info -->
              <div class="space-y-6">
                <h3 class="sr-only">Step 1 of 3: Basic Info - Name and key type</h3>
                <div class="space-y-5">
                  <div>
                    <label for="api-key-name" class="mb-2 block text-sm font-semibold tracking-wide text-default">
                      {m.name()} <span class="text-negative">*</span>
                    </label>
                    <Input.Text
                      id="api-key-name"
                      bind:value={name}
                      placeholder="Production Backend Key"
                      class="!h-12 !text-base"
                    />
                    <p class="mt-2 text-xs text-muted">
                      {m.api_keys_name_help()}
                    </p>
                  </div>

                  <div>
                    <label for="api-key-description" class="mb-2 block text-sm font-semibold tracking-wide text-default">
                      {m.description()}
                    </label>
                    <Input.TextArea
                      id="api-key-description"
                      bind:value={description}
                      placeholder="Used for production backend API integration..."
                      rows={3}
                    />
                  </div>
                </div>

                <!-- Key Type Selection -->
                <fieldset>
                  <legend id="key-type-label" class="mb-3 block text-sm font-semibold tracking-wide text-default">{m.api_keys_key_type()}</legend>
                  <div class="grid gap-3 sm:grid-cols-2" role="group" aria-labelledby="key-type-label">
                    <!-- Secret Key -->
                    <button
                      type="button"
                      onclick={() => (keyType = "sk_")}
                      aria-pressed={keyType === "sk_"}
                      class="group relative rounded-xl border-2 p-5 text-left transition-all duration-200 hover:scale-[1.02] active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:ring-offset-2
                        {keyType === 'sk_'
                          ? 'border-accent-default bg-accent-default/10 ring-2 ring-accent-default/30'
                          : 'border-default bg-primary hover:border-dimmer'}"
                    >
                      <div class="flex items-start gap-4">
                        <div
                          class="flex h-12 w-12 items-center justify-center rounded-lg transition-all duration-200
                            {keyType === 'sk_'
                              ? 'bg-accent-default text-on-fill shadow-lg shadow-accent-default/30'
                              : 'bg-accent-default/15 text-accent-default'}"
                        >
                          <Lock class="h-5 w-5" />
                        </div>
                        <div class="flex-1">
                          <div class="flex items-center gap-2">
                            <span class="text-base font-semibold tracking-wide text-default">{m.api_keys_secret_key()}</span>
                            <span class="rounded-md px-2 py-0.5 text-xs font-mono font-bold bg-accent-default/15 text-accent-default">
                              sk_
                            </span>
                          </div>
                          <p class="mt-1 text-sm leading-relaxed text-muted">
                            {m.api_keys_secret_key_desc()}
                          </p>
                        </div>
                      </div>
                      {#if keyType === "sk_"}
                        <div class="absolute -top-2 -right-2">
                          <div class="flex h-6 w-6 items-center justify-center rounded-full bg-accent-default shadow-lg shadow-accent-default/40">
                            <Check class="h-4 w-4 text-on-fill" strokeWidth={3} />
                          </div>
                        </div>
                      {/if}
                    </button>

                    <!-- Public Key -->
                    <button
                      type="button"
                      onclick={() => (keyType = "pk_")}
                      aria-pressed={keyType === "pk_"}
                      class="group relative rounded-xl border-2 p-5 text-left transition-all duration-200 hover:scale-[1.02] active:scale-[0.98] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:ring-offset-2
                        {keyType === 'pk_'
                          ? 'border-orange-500 bg-orange-500/10 ring-2 ring-orange-500/30'
                          : 'border-default bg-primary hover:border-dimmer'}"
                    >
                      <div class="flex items-start gap-4">
                        <div
                          class="flex h-12 w-12 items-center justify-center rounded-lg transition-all duration-200
                            {keyType === 'pk_'
                              ? 'bg-orange-500 text-white shadow-lg shadow-orange-500/30'
                              : 'bg-orange-500/15 text-orange-600 dark:text-orange-400'}"
                        >
                          <Globe class="h-5 w-5" />
                        </div>
                        <div class="flex-1">
                          <div class="flex items-center gap-2">
                            <span class="text-base font-semibold tracking-wide text-default">{m.api_keys_public_key()}</span>
                            <span class="rounded-md px-2 py-0.5 text-xs font-mono font-bold bg-orange-500/15 text-orange-600 dark:text-orange-400">
                              pk_
                            </span>
                          </div>
                          <p class="mt-1 text-sm leading-relaxed text-muted">
                            {m.api_keys_public_key_desc()}
                          </p>
                        </div>
                      </div>
                      {#if keyType === "pk_"}
                        <div class="absolute -top-2 -right-2">
                          <div class="flex h-6 w-6 items-center justify-center rounded-full bg-orange-500 shadow-lg shadow-orange-500/40">
                            <Check class="h-4 w-4 text-white" strokeWidth={3} />
                          </div>
                        </div>
                      {/if}
                    </button>
                  </div>
                </fieldset>
              </div>

            {:else if currentStep === 2}
              <!-- Step 2: Scope & Permissions -->
              <div class="space-y-6">
                <h3 class="sr-only">Step 2 of 3: Scope and Permissions - Configure access level</h3>
                <!-- Permission Mode Toggle -->
                <div class="flex items-center justify-between pb-4 border-b border-default">
                  <div>
                    <span id="permission-type-label" class="text-sm font-semibold tracking-wide text-default">{m.api_keys_permission_type()}</span>
                    <p class="text-xs mt-0.5 text-muted">{m.api_keys_permission_choose()}</p>
                  </div>
                  <div role="group" aria-labelledby="permission-type-label" class="flex items-center gap-1 rounded-lg p-1 border border-default bg-subtle">
                    <button
                      type="button"
                      onclick={() => (permissionMode = "simple")}
                      class="rounded-md px-4 py-2 text-sm font-medium transition-all
                             {permissionMode === 'simple'
                               ? 'bg-primary text-default shadow-sm'
                               : 'text-muted hover:text-secondary'}"
                    >
                      {m.api_keys_simple()}
                    </button>
                    <button
                      type="button"
                      onclick={() => (permissionMode = "fine-grained")}
                      disabled={keyType === "pk_"}
                      class="rounded-md px-4 py-2 text-sm font-medium transition-all
                             {permissionMode === 'fine-grained'
                               ? 'bg-primary text-default shadow-sm'
                               : keyType === 'pk_'
                                 ? 'text-muted cursor-not-allowed opacity-50'
                                 : 'text-muted hover:text-secondary'}"
                    >
                      {m.api_keys_fine_grained()}
                    </button>
                  </div>
                </div>

                {#if permissionMode === "simple"}
                  <!-- Simple Mode -->
                  <div class="space-y-6">
                    <!-- Scope Type Selection -->
                    <fieldset>
                      <legend id="scope-type-label" class="mb-3 block text-sm font-semibold tracking-wide text-default">{m.api_keys_scope()}</legend>
                      <div class="grid gap-3 grid-cols-2 lg:grid-cols-4" role="group" aria-labelledby="scope-type-label">
                        {#each [
                          { value: "tenant", label: m.api_keys_scope_tenant(), icon: Building2, desc: m.api_keys_scope_tenant_desc() },
                          { value: "space", label: m.api_keys_scope_space(), icon: Building2, desc: m.api_keys_scope_space_desc() },
                          { value: "assistant", label: m.api_keys_scope_assistant(), icon: MessageSquare, desc: m.api_keys_scope_assistant_desc() },
                          { value: "app", label: m.api_keys_scope_app(), icon: AppWindow, desc: m.api_keys_scope_app_desc() }
                        ] as opt}
                          {@const isSelected = scopeType === opt.value}
                          {@const ScopeIcon = opt.icon}
                          <button
                            type="button"
                            onclick={() => (scopeType = opt.value as ApiKeyScopeType)}
                            aria-pressed={isSelected}
                            class="flex flex-col items-center gap-2 rounded-xl border-2 p-4 transition-all duration-200 ease-out focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:ring-offset-2
                                   {isSelected
                                     ? 'border-accent-default bg-accent-default/10 shadow-md shadow-accent-default/20 dark:shadow-accent-default/10'
                                     : 'border-default bg-primary hover:border-dimmer hover:bg-subtle/50'}"
                          >
                            <div
                              class="flex h-10 w-10 items-center justify-center rounded-lg transition-all duration-200 ease-out
                                     {isSelected
                                       ? 'bg-accent-default text-white shadow-sm shadow-accent-default/30'
                                       : 'bg-subtle text-muted'}"
                            >
                              <ScopeIcon class="h-5 w-5" />
                            </div>
                            <div class="text-center">
                              <p class="text-sm font-semibold tracking-wide {isSelected ? 'text-accent-default' : 'text-default'}">
                                {opt.label}
                              </p>
                              <p class="text-[11px] text-muted">{opt.desc}</p>
                            </div>
                          </button>
                        {/each}
                      </div>
                    </fieldset>

                    <!-- Resource Selector -->
                    {#if scopeType !== "tenant"}
                      <div class="rounded-xl border border-default bg-subtle p-5">
                        {#if loadingResources}
                          <!-- Skeleton loading state -->
                          <div class="space-y-3">
                            <div class="flex items-center gap-3">
                              <div class="h-4 w-4 animate-pulse rounded bg-default/50"></div>
                              <div class="h-4 w-24 animate-pulse rounded bg-default/50"></div>
                            </div>
                            {#each [1, 2, 3] as _}
                              <div class="flex items-center gap-3 rounded-lg border border-default bg-primary p-3">
                                <div class="h-8 w-8 animate-pulse rounded-lg bg-default/50"></div>
                                <div class="flex-1 space-y-2">
                                  <div class="h-4 w-32 animate-pulse rounded bg-default/50"></div>
                                  <div class="h-3 w-20 animate-pulse rounded bg-default/30"></div>
                                </div>
                                <div class="h-4 w-4 animate-pulse rounded-full bg-default/50"></div>
                              </div>
                            {/each}
                          </div>
                        {:else}
                          <ScopeResourceSelector
                            {scopeType}
                            bind:value={scopeId}
                            {spaces}
                            {assistants}
                            apps={appOptions}
                          />
                          <div class="mt-4 pt-4 border-t border-default">
                            <button type="button" class="flex items-center gap-2 text-xs text-muted transition-colors mb-2 hover:text-secondary">
                              <Info class="h-3.5 w-3.5" />
                              {m.api_keys_enter_id_manually({ scopeType })}
                            </button>
                            <Input.Text bind:value={manualScopeId} placeholder={m.api_keys_enter_uuid()} class="!font-mono !text-sm" />
                          </div>
                        {/if}
                      </div>
                    {/if}

                    <!-- Simple Permission Level -->
                    <fieldset>
                      <legend id="permission-level-label" class="mb-3 block text-sm font-semibold tracking-wide text-default">{m.api_keys_permission_level()}</legend>
                      <div class="grid gap-3 sm:grid-cols-3" role="radiogroup" aria-labelledby="permission-level-label">
                        {#each [
                          { value: "read", label: m.api_keys_permission_read(), icon: Eye, desc: m.api_keys_permission_read_desc() },
                          { value: "write", label: m.api_keys_permission_write(), icon: Pencil, desc: m.api_keys_permission_write_desc() },
                          { value: "admin", label: m.api_keys_permission_admin(), icon: ShieldCheck, desc: m.api_keys_permission_admin_desc() }
                        ] as opt}
                          {@const isSelected = permission === opt.value}
                          {@const isDisabled = keyType === "pk_" && opt.value !== "read"}
                          {@const PermIcon = opt.icon}
                          {@const levelClasses = opt.value === "read"
                            ? (isSelected ? "border-accent-default bg-accent-default/10" : "border-default bg-primary hover:border-dimmer")
                            : opt.value === "write"
                              ? (isSelected ? "border-purple-500 bg-purple-500/10" : "border-default bg-primary hover:border-dimmer")
                              : (isSelected ? "border-red-500 bg-red-500/10" : "border-default bg-primary hover:border-dimmer")}
                          {@const iconClasses = opt.value === "read"
                            ? (isSelected ? "bg-accent-default text-white" : "bg-accent-default/15 text-accent-default")
                            : opt.value === "write"
                              ? (isSelected ? "bg-purple-500 text-white" : "bg-purple-500/15 text-purple-600 dark:text-purple-400")
                              : (isSelected ? "bg-red-500 text-white" : "bg-red-500/15 text-red-600 dark:text-red-400")}
                          {@const checkBgClass = opt.value === "read"
                            ? "bg-accent-default shadow-accent-default/30"
                            : opt.value === "write"
                              ? "bg-purple-500 shadow-purple-500/30"
                              : "bg-red-500 shadow-red-500/30"}
                          <button
                            type="button"
                            role="radio"
                            aria-checked={isSelected}
                            onclick={() => !isDisabled && (permission = opt.value as ApiKeyPermission)}
                            disabled={isDisabled}
                            class="relative rounded-xl border-2 p-4 text-left transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-default focus-visible:ring-offset-2 {levelClasses}
                                   {isDisabled ? 'opacity-50 cursor-not-allowed' : ''}"
                          >
                            <div class="flex items-center gap-3">
                              <div class="flex h-10 w-10 items-center justify-center rounded-lg transition-colors {iconClasses}">
                                <PermIcon class="h-5 w-5" />
                              </div>
                              <div>
                                <p class="font-semibold tracking-wide text-default">{opt.label}</p>
                                <p class="text-xs text-muted">{opt.desc}</p>
                              </div>
                            </div>
                            {#if isSelected}
                              <div class="absolute -top-1.5 -right-1.5">
                                <div class="flex h-5 w-5 items-center justify-center rounded-full shadow-lg {checkBgClass}">
                                  <Check class="h-3 w-3 text-white" strokeWidth={3} />
                                </div>
                              </div>
                            {/if}
                            {#if isDisabled}
                              <p class="mt-2 text-xs text-yellow-600 dark:text-yellow-400">{m.api_keys_not_available_public()}</p>
                            {/if}
                          </button>
                        {/each}
                      </div>
                    </fieldset>
                  </div>
                {:else}
                  <!-- Fine-grained Mode (HuggingFace style) -->
                  <div class="space-y-5">
                    <!-- Quick actions -->
                    <div class="flex items-center justify-between rounded-lg border border-default bg-secondary/30 px-4 py-3">
                      <div class="flex items-center gap-3">
                        <span class="text-sm text-muted">{m.api_keys_quick_set_all()}</span>
                        <div class="flex gap-1">
                          {#each ["none", "read", "write", "admin"] as level}
                            <button
                              type="button"
                              onclick={() => setAllPermissions(level as ResourcePermission)}
                              class="rounded-md px-3 py-1.5 text-xs font-medium border transition-all hover:shadow-sm focus:outline-none focus:ring-2 focus:ring-accent-default/30 {getLevelClasses(level as ResourcePermission, false)}"
                            >
                              {getLevelLabel(level as ResourcePermission)}
                            </button>
                          {/each}
                        </div>
                      </div>
                      <span class="text-xs text-muted">
                        {m.api_keys_of_enabled({ count: activeResourceCount })}
                      </span>
                    </div>

                    <!-- Two-column permission grid - responsive at md breakpoint -->
                    <div class="grid gap-3 md:grid-cols-2">
                      <!-- Assistants -->
                      <div class="rounded-xl border border-default bg-primary overflow-hidden">
                        <div class="px-5 py-4 bg-gradient-to-b from-subtle to-primary/50 border-b border-default/60">
                          <div class="flex items-center justify-between">
                            <div class="flex items-center gap-3">
                              <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-primary border border-default/80 shadow-sm">
                                <MessageSquare class="h-5 w-5 text-secondary" />
                              </div>
                              <div>
                                <h4 class="font-semibold text-sm text-default">{m.api_keys_resource_assistants()}</h4>
                                <p class="text-xs text-muted">{m.api_keys_resource_assistants_desc()}</p>
                              </div>
                            </div>
                            <span class="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold transition-all duration-200 {getLevelBadgeClasses(assistantsPermission)}">
                              {getLevelLabel(assistantsPermission)}
                            </span>
                          </div>
                        </div>
                        <div class="px-5 py-4">
                          <div class="flex gap-2">
                            {#each ["none", "read", "write", "admin"] as level}
                              <button
                                type="button"
                                onclick={() => (assistantsPermission = level as ResourcePermission)}
                                class="flex-1 rounded-lg px-3 py-2 text-xs font-medium border-2 transition-all focus:outline-none focus:ring-2 focus:ring-accent-default/30 {getLevelClasses(level as ResourcePermission, assistantsPermission === level)}"
                              >
                                {getLevelLabel(level as ResourcePermission)}
                              </button>
                            {/each}
                          </div>
                        </div>
                      </div>

                      <!-- Apps -->
                      <div class="rounded-xl border border-default bg-primary overflow-hidden permission-card-enter">
                        <div class="px-5 py-4 bg-gradient-to-b from-subtle to-primary/50 border-b border-default/60">
                          <div class="flex items-center justify-between">
                            <div class="flex items-center gap-3">
                              <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-primary border border-default/80 shadow-sm">
                                <AppWindow class="h-5 w-5 text-secondary" />
                              </div>
                              <div>
                                <h4 class="font-semibold text-sm text-default">{m.api_keys_resource_applications()}</h4>
                                <p class="text-xs text-muted">{m.api_keys_resource_applications_desc()}</p>
                              </div>
                            </div>
                            <span class="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold transition-all duration-200 {getLevelBadgeClasses(appsPermission)}">
                              {getLevelLabel(appsPermission)}
                            </span>
                          </div>
                        </div>
                        <div class="px-5 py-4">
                          <div class="flex gap-2">
                            {#each ["none", "read", "write", "admin"] as level}
                              <button
                                type="button"
                                onclick={() => (appsPermission = level as ResourcePermission)}
                                class="flex-1 rounded-lg px-3 py-2 text-xs font-medium border-2 transition-all focus:outline-none focus:ring-2 focus:ring-accent-default/30 {getLevelClasses(level as ResourcePermission, appsPermission === level)}"
                              >
                                {getLevelLabel(level as ResourcePermission)}
                              </button>
                            {/each}
                          </div>
                        </div>
                      </div>

                      <!-- Spaces -->
                      <div class="rounded-xl border border-default bg-primary overflow-hidden permission-card-enter">
                        <div class="px-5 py-4 bg-gradient-to-b from-subtle to-primary/50 border-b border-default/60">
                          <div class="flex items-center justify-between">
                            <div class="flex items-center gap-3">
                              <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-primary border border-default/80 shadow-sm">
                                <Building2 class="h-5 w-5 text-secondary" />
                              </div>
                              <div>
                                <h4 class="font-semibold text-sm text-default">{m.api_keys_resource_spaces()}</h4>
                                <p class="text-xs text-muted">{m.api_keys_resource_spaces_desc()}</p>
                              </div>
                            </div>
                            <span class="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold transition-all duration-200 {getLevelBadgeClasses(spacesPermission)}">
                              {getLevelLabel(spacesPermission)}
                            </span>
                          </div>
                        </div>
                        <div class="px-5 py-4">
                          <div class="flex gap-2">
                            {#each ["none", "read", "write", "admin"] as level}
                              <button
                                type="button"
                                onclick={() => (spacesPermission = level as ResourcePermission)}
                                class="flex-1 rounded-lg px-3 py-2 text-xs font-medium border-2 transition-all focus:outline-none focus:ring-2 focus:ring-accent-default/30 {getLevelClasses(level as ResourcePermission, spacesPermission === level)}"
                              >
                                {getLevelLabel(level as ResourcePermission)}
                              </button>
                            {/each}
                          </div>
                        </div>
                      </div>

                      <!-- Knowledge -->
                      <div class="rounded-xl border border-default bg-primary overflow-hidden permission-card-enter">
                        <div class="px-5 py-4 bg-gradient-to-b from-subtle to-primary/50 border-b border-default/60">
                          <div class="flex items-center justify-between">
                            <div class="flex items-center gap-3">
                              <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-primary border border-default/80 shadow-sm">
                                <Sparkles class="h-5 w-5 text-secondary" />
                              </div>
                              <div>
                                <h4 class="font-semibold text-sm text-default">{m.api_keys_resource_knowledge()}</h4>
                                <p class="text-xs text-muted">{m.api_keys_resource_knowledge_desc()}</p>
                              </div>
                            </div>
                            <span class="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold transition-all duration-200 {getLevelBadgeClasses(knowledgePermission)}">
                              {getLevelLabel(knowledgePermission)}
                            </span>
                          </div>
                        </div>
                        <div class="px-5 py-4">
                          <div class="flex gap-2">
                            {#each ["none", "read", "write", "admin"] as level}
                              <button
                                type="button"
                                onclick={() => (knowledgePermission = level as ResourcePermission)}
                                class="flex-1 rounded-lg px-3 py-2 text-xs font-medium border-2 transition-all focus:outline-none focus:ring-2 focus:ring-accent-default/30 {getLevelClasses(level as ResourcePermission, knowledgePermission === level)}"
                              >
                                {getLevelLabel(level as ResourcePermission)}
                              </button>
                            {/each}
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- Info note -->
                    <div class="flex items-start gap-3 rounded-lg border border-accent-default/30 bg-accent-default/5 px-4 py-3">
                      <Info class="h-4 w-4 flex-shrink-0 mt-0.5 text-accent-default" />
                      <p class="text-xs leading-relaxed text-accent-default">
                        {@html m.api_keys_fine_grained_info()}
                      </p>
                    </div>
                  </div>
                {/if}
              </div>

            {:else if currentStep === 3}
              <!-- Step 3: Security Settings -->
              <div class="space-y-6">
                <h3 class="sr-only">Step 3 of 3: Security Settings - Configure origins, IPs, and expiration</h3>
                {#if keyType === "pk_"}
                  <TagInput
                    type="origin"
                    bind:value={allowedOrigins}
                    label="Allowed Origins"
                    description="Domains that can use this key (required for public keys)"
                    placeholder="https://example.com"
                    required
                  />
                {/if}

                {#if keyType === "sk_"}
                  <TagInput
                    type="ip"
                    bind:value={allowedIps}
                    label="Allowed IPs"
                    description="IP addresses or CIDR ranges that can use this key (optional)"
                    placeholder="192.168.1.0/24"
                  />
                {/if}

                <ExpirationPicker bind:value={expiresAt} />

                <div>
                  <label for="api-key-rate-limit" class="mb-2 block text-sm font-semibold tracking-wide text-default">
                    {m.api_keys_rate_limit()}
                  </label>
                  <Input.Text
                    id="api-key-rate-limit"
                    bind:value={rateLimit}
                    placeholder={m.api_keys_rate_limit_placeholder()}
                    type="number"
                    min="1"
                    class="!h-11"
                  />
                  <p class="mt-2 text-xs text-muted">
                    {m.api_keys_rate_limit_help()}
                  </p>
                </div>
              </div>
            {/if}
          </div>
        {/key}
      </div>
    </div>

    <!-- Footer -->
    <div class="flex-shrink-0 flex flex-wrap items-center justify-between gap-3 px-6 py-4 border-t border-default bg-subtle rounded-b-2xl">
      <div class="flex-shrink-0">
        {#if currentStep > 1}
          <Button variant="ghost" on:click={prevStep} class="gap-2">
            <ChevronLeft class="h-4 w-4" />
            {m.api_keys_back()}
          </Button>
        {/if}
      </div>

      <div class="flex flex-wrap items-center gap-2 sm:gap-3">
        <Dialog.Close asChild let:close>
          <Button is={close} variant="outlined">{m.cancel()}</Button>
        </Dialog.Close>

        {#if currentStep < totalSteps}
          <Button variant="primary" on:click={nextStep} class="gap-2 min-w-[80px] sm:min-w-[100px]">
            {m.api_keys_next()}
            <ChevronRight class="h-4 w-4" />
          </Button>
        {:else}
          <Button variant="primary" on:click={createKey} disabled={isSubmitting} class="gap-2 min-w-[100px] sm:min-w-[140px] {isSubmitting ? 'submit-pulse' : ''}">
            {#if isSubmitting}
              <div class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></div>
              <span class="hidden sm:inline">{m.api_keys_creating()}</span>
            {:else}
              <Key class="h-4 w-4" />
              <span class="hidden sm:inline">{m.api_keys_create()}</span>
              <span class="sm:hidden">{m.api_keys_create_short()}</span>
            {/if}
          </Button>
        {/if}
      </div>
    </div>
  </Dialog.Content>
</Dialog.Root>

<style>
  /* Step indicator bounce animation */
  @keyframes step-bounce {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.08); }
  }

  :global(.step-bounce) {
    animation: step-bounce 0.3s ease-out;
  }

  /* Staggered entrance for fine-grained permission cards */
  @keyframes card-entrance {
    from {
      opacity: 0;
      transform: translateY(8px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  :global(.permission-card-enter) {
    animation: card-entrance 0.25s ease-out forwards;
  }

  :global(.permission-card-enter:nth-child(1)) { animation-delay: 0ms; }
  :global(.permission-card-enter:nth-child(2)) { animation-delay: 50ms; }
  :global(.permission-card-enter:nth-child(3)) { animation-delay: 100ms; }
  :global(.permission-card-enter:nth-child(4)) { animation-delay: 150ms; }

  /* Submit button pulse animation when loading */
  @keyframes submit-pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.85; }
  }

  :global(.submit-pulse) {
    animation: submit-pulse 1.5s ease-in-out infinite;
  }
</style>
