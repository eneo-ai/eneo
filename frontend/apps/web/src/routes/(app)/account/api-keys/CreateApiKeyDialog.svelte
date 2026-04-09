<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { SvelteMap } from "svelte/reactivity";
  import type {
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyType,
    ResourcePermissionLevel,
    SpaceSparse
  } from "@intric/intric-js";
  import { toast } from "svelte-sonner";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { getIntric } from "$lib/core/Intric";
  import { getAppContext } from "$lib/core/AppContext";
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
    Sparkles,
    Copy,
    CheckCircle2,
    Ban,
    Link2
  } from "lucide-svelte";
  import { fly, fade } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import ScopeResourceSelector from "./ScopeResourceSelector.svelte";
  import TagInput from "./TagInput.svelte";
  import ExpirationPicker from "./ExpirationPicker.svelte";

  const intric = getIntric();
  const { user } = getAppContext();
  const isAdmin = user.hasPermission("admin");

  let {
    onCreated,
    lockedScopeType,
    lockedScopeId,
    lockedScopeName,
    triggerVariant = "primary"
  }: {
    onCreated?: () => void;
    lockedScopeType?: ApiKeyScopeType;
    lockedScopeId?: string;
    lockedScopeName?: string;
    triggerVariant?: "primary" | "outlined";
  } = $props();

  const scopeLocked = $derived(!!lockedScopeType && !!lockedScopeId);
  const LockedScopeIcon = $derived(getScopeIcon(lockedScopeType));

  let showDialog = $state(false);
  let isSubmitting = $state(false);
  let errorMessage = $state<string | null>(null);
  let createdSecret = $state<string | null>(null);
  let createdResponse = $state<ApiKeyCreatedResponse | null>(null);
  let secretCopied = $state(false);

  // Wizard step state
  let currentStep = $state(1);
  const totalSteps = 3;
  let stepDirection = $state<"forward" | "backward">("forward");

  // Step 1: Basic info
  let name = $state("");
  let description = $state("");
  let keyType = $state<ApiKeyType>("sk_");

  // Step 2: Scope & permissions
  let ownership = $state<"user" | "service">("user");
  let permission = $state<ApiKeyPermission>("read");
  let scopeType = $state<ApiKeyScopeType>(untrack(() => lockedScopeType ?? "tenant"));
  let scopeId = $state<string | null>(untrack(() => lockedScopeId ?? null));
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

  // Creation constraints from tenant policy
  let requireExpiration = $state(false);
  let maxExpirationDays = $state<number | null>(null);
  let maxRateLimit = $state<number | null>(null);

  // Resources for scope selection
  type ResourceOption = { id: string; name: string; spaceName?: string };
  let spaces = $state<SpaceSparse[]>([]);
  let assistantOptions = $state<ResourceOption[]>([]);
  let appOptions = $state<ResourceOption[]>([]);
  let loadingResources = $state(false);

  // Step definitions - using a getter function to access translations
  const getSteps = () => [
    {
      number: 1,
      title: m.api_keys_step_basic_info(),
      icon: Key,
      subtitle: m.api_keys_step_basic_subtitle()
    },
    {
      number: 2,
      title: m.api_keys_step_scope(),
      icon: Shield,
      subtitle: m.api_keys_step_scope_subtitle()
    },
    {
      number: 3,
      title: m.api_keys_step_security(),
      icon: Settings2,
      subtitle: m.api_keys_step_security_subtitle()
    }
  ];
  const steps = $derived(getSteps());

  // Transition config
  const transitionDuration = 250;
  const flyX = $derived(stepDirection === "forward" ? 30 : -30);

  // Count active fine-grained permissions
  const activeResourceCount = $derived(
    [assistantsPermission, appsPermission, spacesPermission, knowledgePermission].filter(
      (p) => p !== "none"
    ).length
  );

  // Effect: Reset permission to read for public keys
  $effect(() => {
    if (keyType === "pk_" && permission !== "read") {
      permission = "read";
      permissionMode = "simple";
    }
  });

  // Effect: Clamp fine-grained permissions when base permission is lowered
  $effect(() => {
    if (permissionMode === "fine-grained") {
      assistantsPermission = clampToPermission(assistantsPermission);
      appsPermission = clampToPermission(appsPermission);
      spacesPermission = clampToPermission(spacesPermission);
      knowledgePermission = clampToPermission(knowledgePermission);
    }
  });

  // Effect: Reset scope ID when scope type changes (skip when scope is locked)
  $effect(() => {
    if (scopeType && !scopeLocked) {
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
      const scrollArea = document.querySelector(".step-content-scroll");
      if (scrollArea) {
        scrollArea.scrollTop = 0;
      }
    }
  });

  async function loadResources() {
    loadingResources = true;
    try {
      let listedSpaces: SpaceSparse[] = [];

      try {
        listedSpaces = await intric.spaces.list({
          include_personal: true,
          include_applications: true
        });
      } catch (error) {
        console.error(error);
      }

      if (listedSpaces.length === 0) {
        try {
          listedSpaces = await intric.spaces.list();
        } catch (error) {
          console.error(error);
        }
      }

      const spaceById = new SvelteMap<string, SpaceSparse>();
      for (const space of listedSpaces) {
        spaceById.set(space.id, space);
      }

      try {
        const personalSpace = await intric.spaces.getPersonalSpace();
        if (personalSpace && !spaceById.has(personalSpace.id)) {
          spaceById.set(personalSpace.id, personalSpace);
        }
      } catch (error) {
        console.error(error);
      }

      try {
        const orgSpace = await intric.spaces.getOrganizationSpace();
        if (orgSpace && !spaceById.has(orgSpace.id)) {
          spaceById.set(orgSpace.id, orgSpace);
        }
      } catch (error) {
        console.error(error);
      }

      spaces = Array.from(spaceById.values());

      const applicationsBySpace = await Promise.all(
        spaces.map(async (space) => {
          try {
            const applications = await intric.spaces.listApplications({ id: space.id });
            return { space, applications };
          } catch (error) {
            console.error(error);
            return { space, applications: space.applications ?? null };
          }
        })
      );

      assistantOptions = applicationsBySpace.flatMap(({ space, applications }) =>
        (applications?.assistants?.items ?? []).map((assistant) => ({
          id: assistant.id,
          name: assistant.name,
          spaceName: space.name
        }))
      );

      appOptions = applicationsBySpace.flatMap(({ space, applications }) =>
        (applications?.apps?.items ?? []).map((app) => ({
          id: app.id,
          name: app.name,
          spaceName: space.name
        }))
      );

      if (assistantOptions.length === 0) {
        const assistants = await intric.assistants.list();
        assistantOptions = assistants.map((assistant) => ({
          id: assistant.id,
          name: assistant.name
        }));
      }
    } catch (error) {
      console.error(error);
    } finally {
      loadingResources = false;
    }
  }

  async function loadCreationConstraints() {
    try {
      const constraints = await intric.apiKeys.getCreationConstraints();
      requireExpiration = constraints.require_expiration ?? false;
      maxExpirationDays = constraints.max_expiration_days ?? null;
      maxRateLimit = constraints.max_rate_limit ?? null;
    } catch {
      // Non-critical: defaults are safe (no restriction)
    }
  }

  onMount(() => {
    if (!scopeLocked) {
      void loadResources();
    }
    void loadCreationConstraints();
  });

  function validateStep(step: number): string | null {
    switch (step) {
      case 1:
        if (!name.trim()) return m.api_keys_name_required();
        return null;
      case 2:
        if (!scopeLocked && scopeType !== "tenant" && !scopeId && !manualScopeId.trim()) {
          return m.api_keys_select_scope({ scopeType });
        }
        return null;
      case 3:
        if (keyType === "pk_" && allowedOrigins.length === 0) {
          return m.api_keys_origin_required();
        }
        if (requireExpiration && !expiresAt) {
          return m.api_keys_exp_required();
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
      scope_id: scopeType === "tenant" ? null : scopeId || manualScopeId.trim() || null,
      ownership: ownership,
      allowed_origins: keyType === "pk_" && allowedOrigins.length > 0 ? allowedOrigins : null,
      allowed_ips: keyType === "sk_" && allowedIps.length > 0 ? allowedIps : null,
      expires_at: expiresAt,
      rate_limit: rateLimit ? Number(rateLimit) : null,
      resource_permissions:
        permissionMode === "fine-grained"
          ? {
              assistants: assistantsPermission as ResourcePermissionLevel,
              apps: appsPermission as ResourcePermissionLevel,
              spaces: spacesPermission as ResourcePermissionLevel,
              knowledge: knowledgePermission as ResourcePermissionLevel
            }
          : null
    };

    try {
      const response = await intric.apiKeys.create(request);
      createdSecret = response.secret;
      createdResponse = response;
      secretCopied = false;
      currentStep = 4;
    } catch (error: unknown) {
      console.error(error);
      const err = error as { getReadableMessage?: () => string };
      errorMessage = err?.getReadableMessage?.() ?? m.something_went_wrong();
    } finally {
      isSubmitting = false;
    }
  }

  async function copySecret() {
    if (!createdSecret) return;
    try {
      await navigator.clipboard.writeText(createdSecret);
      secretCopied = true;
      toast.success(m.api_keys_copied_message());
      setTimeout(() => (secretCopied = false), 2000);
    } catch {
      toast.error(m.something_went_wrong());
    }
  }

  function finishAndClose() {
    if (createdResponse && onCreated) {
      onCreated();
      // Prevent duplicate callback when the dialog emits on:close next.
      createdResponse = null;
    }
    showDialog = false;
    resetForm();
  }

  function resetForm() {
    currentStep = 1;
    stepDirection = "forward";
    name = "";
    description = "";
    keyType = "sk_";
    ownership = "user";
    permission = "read";
    permissionMode = "simple";
    assistantsPermission = "none";
    appsPermission = "none";
    spacesPermission = "none";
    knowledgePermission = "none";
    scopeType = lockedScopeType ?? "tenant";
    scopeId = lockedScopeId ?? null;
    manualScopeId = "";
    allowedOrigins = [];
    allowedIps = [];
    expiresAt = null;
    rateLimit = "";
    createdSecret = null;
    createdResponse = null;
    secretCopied = false;
    errorMessage = null;
  }

  function handleOpenChange(open: boolean) {
    if (!open) {
      if (createdResponse && onCreated) {
        onCreated();
      }
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

  // Permission level display config — uses eneo's semantic state tokens
  // (warning = elevated write access, negative = destructive admin) so the
  // colours match ApiKeyTable's permission badges and render identically
  // across browsers (raw `purple-*`/`red-*` palettes go through Tailwind v4
  // oklch() + color-mix() opacity which Chrome and Firefox gamut-map
  // differently).
  function getLevelClasses(level: ResourcePermission, isSelected: boolean): string {
    if (!isSelected)
      return "border-default bg-primary text-muted hover:border-dimmer hover:bg-subtle";
    switch (level) {
      case "none":
        return "border-stronger bg-subtle text-default";
      case "read":
        return "border-accent-default bg-accent-default/10 text-accent-default";
      case "write":
        return "border-warning-default bg-warning-default/10 text-warning-stronger";
      case "admin":
        return "border-negative-default bg-negative-default/10 text-negative-stronger";
    }
  }

  function getLevelBadgeClasses(level: ResourcePermission): string {
    switch (level) {
      case "none":
        return "bg-subtle text-default";
      case "read":
        return "bg-accent-default/15 text-accent-default";
      case "write":
        return "bg-warning-default/15 text-warning-stronger";
      case "admin":
        return "bg-negative-default/15 text-negative-stronger";
    }
  }

  function getLevelLabel(level: ResourcePermission) {
    switch (level) {
      case "none":
        return m.api_keys_permission_no_access();
      case "read":
        return m.api_keys_permission_read();
      case "write":
        return m.api_keys_permission_write();
      case "admin":
        return m.api_keys_permission_admin();
    }
  }

  // Scope icon helper for locked-scope display
  function getScopeIcon(type: ApiKeyScopeType | undefined) {
    switch (type) {
      case "space":
        return Building2;
      case "assistant":
        return MessageSquare;
      case "app":
        return AppWindow;
      default:
        return Building2;
    }
  }

  function getScopeLabel(type: ApiKeyScopeType | undefined) {
    switch (type) {
      case "space":
        return m.api_keys_scope_space();
      case "assistant":
        return m.api_keys_scope_assistant();
      case "app":
        return m.api_keys_scope_app();
      default:
        return m.api_keys_scope_tenant();
    }
  }

  // Permission level ordering for ceiling enforcement
  const permissionOrder: Record<string, number> = {
    none: 0,
    read: 1,
    write: 2,
    admin: 3
  };

  function isLevelAllowed(level: ResourcePermission): boolean {
    return permissionOrder[level] <= permissionOrder[permission];
  }

  // Clamp a resource permission to the ceiling
  function clampToPermission(level: ResourcePermission): ResourcePermission {
    if (permissionOrder[level] > permissionOrder[permission]) {
      return permission as ResourcePermission;
    }
    return level;
  }
</script>

<Dialog.Root
  bind:open={showDialog}
  onOpenChange={(open) => {
    if (!open) handleOpenChange(false);
  }}
>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant={triggerVariant === "outlined" ? "outline" : "default"}>
        <Key />
        {m.generate_api_key()}
      </Button>
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content
    class="bg-primary !flex max-h-[90vh] !max-w-4xl flex-col overflow-hidden !rounded-2xl !p-0"
  >
    {#if currentStep <= totalSteps}
      <!-- Header with subtle gradient -->
      <div
        class="from-subtle to-primary flex-shrink-0 rounded-t-2xl bg-gradient-to-b px-6 pt-6 pb-5"
      >
        <Dialog.Title class="text-default text-2xl font-bold tracking-tight">
          {scopeLocked && lockedScopeName
            ? `${m.generate_new_api_key_title()} — ${lockedScopeName}`
            : m.generate_new_api_key_title()}
        </Dialog.Title>
        <div class="text-secondary mt-2 max-w-xl text-sm leading-relaxed">
          <Dialog.Description>
            <!-- eslint-disable-next-line svelte/no-at-html-tags -- localized warning is trusted i18n content -->
            {@html m.generate_api_key_warning()}
          </Dialog.Description>
        </div>

        <!-- Step indicator - improved contrast and accessibility (WCAG 2.2 AA) -->
        <nav
          class="mt-6 hidden items-center justify-between sm:flex"
          aria-label="API key creation progress"
        >
          <ol class="flex w-full items-center justify-between" role="list">
            {#each steps as step, index (step.number)}
              {@const isActive = currentStep === step.number}
              {@const isCompleted = currentStep > step.number}
              {@const canNavigate =
                step.number <= currentStep ||
                (step.number === currentStep + 1 && isStepComplete(currentStep))}
              {@const StepIcon = step.icon}

              <li class="flex items-center {index < steps.length - 1 ? 'flex-1' : ''}">
                <button
                  type="button"
                  onclick={() => goToStep(step.number)}
                  disabled={!canNavigate}
                  aria-label="Step {step.number}: {step.title}"
                  aria-current={isActive ? "step" : undefined}
                  class="group focus-visible:ring-accent-default flex items-center gap-3 rounded-xl px-4 py-3 transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2
                  {isActive ? 'bg-accent-default/10' : ''}
                  {canNavigate ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'}"
                >
                  <div
                    class="relative flex h-10 w-10 items-center justify-center rounded-full border-2 transition-all duration-200
                    {isActive
                      ? 'border-accent-default bg-accent-default text-on-fill shadow-accent-default/40 step-bounce shadow-lg'
                      : ''}
                    {isCompleted
                      ? 'border-positive-default bg-positive-default/10 text-positive-stronger'
                      : ''}
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
                      {isCompleted ? 'text-positive-stronger' : ''}
                      {!isActive && !isCompleted ? 'text-default' : ''}"
                    >
                      {step.title}
                    </p>
                    <p class="text-secondary text-xs">{step.subtitle}</p>
                  </div>
                </button>

                {#if index < steps.length - 1}
                  <div class="mx-3 flex-1" aria-hidden="true">
                    <div
                      class="h-1 w-full rounded-full transition-all duration-300
                      {isCompleted ? 'bg-positive-default' : 'bg-tertiary'}"
                    ></div>
                  </div>
                {/if}
              </li>
            {/each}
          </ol>
        </nav>

        <!-- Mobile step dots -->
        <div class="mt-4 flex justify-center gap-2 sm:hidden">
          {#each steps as step (step.number)}
            {@const isActive = currentStep === step.number}
            {@const isCompleted = currentStep > step.number}
            <button
              type="button"
              onclick={() => goToStep(step.number)}
              disabled={step.number > currentStep + 1}
              class="h-2.5 w-2.5 rounded-full transition-all duration-200
              {isActive ? 'bg-accent-default scale-125' : ''}
              {isCompleted ? 'bg-positive-default' : ''}
              {!isActive && !isCompleted ? 'bg-tertiary' : ''}
              disabled:opacity-40"
              aria-label="Step {step.number}"
            ></button>
          {/each}
        </div>
        <p class="text-default mt-2 text-center text-sm font-medium sm:hidden">
          {steps[currentStep - 1].title}
        </p>
      </div>

      <!-- Error message - sticky outside scrollable area -->
      {#if errorMessage}
        <div
          class="mx-6 mt-4 mb-3 flex-shrink-0"
          transition:fly={{ y: -8, duration: 180, easing: cubicOut }}
        >
          <Alert.Root variant="destructive" aria-live="assertive">
            <AlertCircle />
            <Alert.Description>{errorMessage}</Alert.Description>
          </Alert.Root>
        </div>
      {/if}

      <!-- Step content - scrollable area with aria-live for screen reader announcements -->
      <div
        class="step-content-scroll min-h-0 flex-1 overflow-y-auto scroll-smooth px-6 pt-4 pb-5"
        aria-live="polite"
        aria-atomic="false"
      >
        <div class="grid items-start py-2" style="grid-template: 1fr / 1fr;">
          {#key currentStep}
            <div
              in:fly={{
                x: flyX,
                duration: transitionDuration,
                delay: transitionDuration * 0.4,
                easing: cubicOut
              }}
              out:fade={{ duration: transitionDuration * 0.35 }}
              class="w-full"
              style="grid-area: 1 / 1; will-change: transform, opacity;"
            >
              {#if currentStep === 1}
                <!-- Step 1: Basic Info -->
                <div class="space-y-6">
                  <h3 class="sr-only">{m.api_keys_step_basic_sr()}</h3>
                  <div class="space-y-5">
                    <div>
                      <label
                        for="api-key-name"
                        class="text-default mb-2 block text-sm font-semibold tracking-wide"
                      >
                        {m.name()} <span class="text-negative-stronger">*</span>
                      </label>
                      <Input
                        id="api-key-name"
                        bind:value={name}
                        placeholder={m.api_keys_name_placeholder()}
                        class="h-12 text-base"
                      />
                      <p class="text-muted mt-2 text-xs">
                        {m.api_keys_name_help()}
                      </p>
                    </div>

                    <div>
                      <label
                        for="api-key-description"
                        class="text-default mb-2 block text-sm font-semibold tracking-wide"
                      >
                        {m.description()}
                      </label>
                      <Textarea
                        id="api-key-description"
                        bind:value={description}
                        placeholder={m.api_keys_description_placeholder()}
                        rows={3}
                      />
                    </div>
                  </div>

                  <!-- Key Type Selection -->
                  <fieldset>
                    <legend
                      id="key-type-label"
                      class="text-default mb-3 block text-sm font-semibold tracking-wide"
                      >{m.api_keys_key_type()}</legend
                    >
                    <div
                      class="grid gap-3 sm:grid-cols-2"
                      role="group"
                      aria-labelledby="key-type-label"
                    >
                      <!-- Secret Key -->
                      <button
                        type="button"
                        onclick={() => (keyType = "sk_")}
                        aria-pressed={keyType === "sk_"}
                        class="group focus-visible:ring-accent-default relative rounded-xl border-2 p-5 text-left transition-all duration-200 hover:scale-[1.02] focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 active:scale-[0.98]
                        {keyType === 'sk_'
                          ? 'border-accent-default bg-accent-default/10 ring-accent-default/30 ring-2'
                          : 'border-default bg-primary hover:border-dimmer'}"
                      >
                        <div class="flex items-start gap-4">
                          <div
                            class="flex h-12 w-12 items-center justify-center rounded-lg transition-all duration-200
                            {keyType === 'sk_'
                              ? 'bg-accent-default text-on-fill shadow-accent-default/30 shadow-lg'
                              : 'bg-accent-default/15 text-accent-default'}"
                          >
                            <Lock class="h-5 w-5" />
                          </div>
                          <div class="flex-1">
                            <div class="flex items-center gap-2">
                              <span class="text-default text-base font-semibold tracking-wide"
                                >{m.api_keys_secret_key()}</span
                              >
                              <span
                                class="bg-accent-default/15 text-accent-default rounded-md px-2 py-0.5 font-mono text-xs font-bold"
                              >
                                sk_
                              </span>
                            </div>
                            <p class="text-muted mt-1 text-sm leading-relaxed">
                              {m.api_keys_secret_key_desc()}
                            </p>
                          </div>
                        </div>
                        {#if keyType === "sk_"}
                          <div class="absolute -top-2 -right-2">
                            <div
                              class="bg-accent-default shadow-accent-default/40 flex h-6 w-6 items-center justify-center rounded-full shadow-lg"
                            >
                              <Check class="text-on-fill h-4 w-4" strokeWidth={3} />
                            </div>
                          </div>
                        {/if}
                      </button>

                      <!-- Public Key -->
                      <!-- Wraps in `label-amethyst` so the inner `*-label-*`
                           utilities resolve to eneo's amethyst palette,
                           matching ApiKeyTable's public-key avatar without
                           introducing new tokens. -->
                      <button
                        type="button"
                        onclick={() => (keyType = "pk_")}
                        aria-pressed={keyType === "pk_"}
                        class="label-amethyst group focus-visible:ring-accent-default relative rounded-xl border-2 p-5 text-left transition-all duration-200 hover:scale-[1.02] focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 active:scale-[0.98]
                        {keyType === 'pk_'
                          ? 'border-label-default bg-label-default/10 ring-label-default/30 ring-2'
                          : 'border-default bg-primary hover:border-dimmer'}"
                      >
                        <div class="flex items-start gap-4">
                          <div
                            class="flex h-12 w-12 items-center justify-center rounded-lg transition-all duration-200
                            {keyType === 'pk_'
                              ? 'bg-label-default text-on-fill shadow-label-default/30 shadow-lg'
                              : 'bg-label-dimmer text-label-stronger'}"
                          >
                            <Globe class="h-5 w-5" />
                          </div>
                          <div class="flex-1">
                            <div class="flex items-center gap-2">
                              <span class="text-default text-base font-semibold tracking-wide"
                                >{m.api_keys_public_key()}</span
                              >
                              <span
                                class="bg-label-dimmer text-label-stronger rounded-md px-2 py-0.5 font-mono text-xs font-bold"
                              >
                                pk_
                              </span>
                            </div>
                            <p class="text-muted mt-1 text-sm leading-relaxed">
                              {m.api_keys_public_key_desc()}
                            </p>
                          </div>
                        </div>
                        {#if keyType === "pk_"}
                          <div class="absolute -top-2 -right-2">
                            <div
                              class="bg-label-default shadow-label-default/40 flex h-6 w-6 items-center justify-center rounded-full shadow-lg"
                            >
                              <Check class="text-on-fill h-4 w-4" strokeWidth={3} />
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
                  <h3 class="sr-only">{m.api_keys_step_scope_sr()}</h3>
                  <!-- Permission Mode Toggle (hidden for public keys: only simple mode is supported) -->
                  {#if keyType !== "pk_"}
                    <div class="border-default flex items-center justify-between border-b pb-4">
                      <div>
                        <span
                          id="permission-type-label"
                          class="text-default text-sm font-semibold tracking-wide"
                          >{m.api_keys_permission_type()}</span
                        >
                        <p class="text-muted mt-0.5 text-xs">{m.api_keys_permission_choose()}</p>
                      </div>
                      <div
                        role="group"
                        aria-labelledby="permission-type-label"
                        class="border-default bg-subtle flex items-center gap-1 rounded-lg border p-1"
                      >
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
                          class="rounded-md px-4 py-2 text-sm font-medium transition-all
                               {permissionMode === 'fine-grained'
                            ? 'bg-primary text-default shadow-sm'
                            : 'text-muted hover:text-secondary'}"
                        >
                          {m.api_keys_fine_grained()}
                        </button>
                      </div>
                    </div>
                  {/if}

                  <!-- Key Ownership Toggle (admin only) -->
                  {#if isAdmin}
                    <div class="border-default flex items-center justify-between border-b pb-4">
                      <div>
                        <span
                          id="ownership-label"
                          class="text-default text-sm font-semibold tracking-wide"
                          >{m.api_keys_ownership_label()}</span
                        >
                        <p class="text-muted mt-0.5 text-xs">
                          {ownership === "service"
                            ? m.api_keys_ownership_service_desc()
                            : m.api_keys_ownership_user_desc()}
                        </p>
                      </div>
                      <div
                        role="group"
                        aria-labelledby="ownership-label"
                        class="border-default bg-subtle flex items-center gap-1 rounded-lg border p-1"
                      >
                        <button
                          type="button"
                          onclick={() => (ownership = "user")}
                          class="rounded-md px-4 py-2 text-sm font-medium transition-all
                               {ownership === 'user'
                            ? 'bg-primary text-default shadow-sm'
                            : 'text-muted hover:text-secondary'}"
                        >
                          {m.api_keys_ownership_user()}
                        </button>
                        <button
                          type="button"
                          onclick={() => (ownership = "service")}
                          class="rounded-md px-4 py-2 text-sm font-medium transition-all
                               {ownership === 'service'
                            ? 'bg-primary text-default shadow-sm'
                            : 'text-muted hover:text-secondary'}"
                        >
                          {m.api_keys_ownership_service()}
                        </button>
                      </div>
                    </div>
                    {#if ownership === "service" && scopeType === "tenant" && (permission === "write" || permission === "admin")}
                      <div
                        class="border-warning-default/40 bg-warning-dimmer/40 text-warning-stronger dark:bg-warning-dimmer/20 rounded-lg border p-3 text-xs"
                      >
                        <span class="inline-flex items-center gap-1.5">
                          <AlertCircle class="h-3.5 w-3.5" />
                          {m.api_keys_ownership_service_guardrail_hint()}
                        </span>
                      </div>
                    {/if}
                  {/if}

                  {#if permissionMode === "simple"}
                    <!-- Simple Mode -->
                    <div class="space-y-6">
                      {#if scopeLocked}
                        <!-- Locked scope indicator — contextual creation mode -->
                        <div
                          class="border-accent-default/20 bg-accent-default/5 rounded-xl border p-4"
                        >
                          <div class="flex items-center gap-3">
                            <div
                              class="bg-accent-default/15 flex h-10 w-10 items-center justify-center rounded-lg"
                            >
                              <LockedScopeIcon class="text-accent-default h-5 w-5" />
                            </div>
                            <div>
                              <p class="text-default text-sm font-semibold">{lockedScopeName}</p>
                              <p class="text-muted text-xs">
                                {getScopeLabel(lockedScopeType)} · {m.api_keys_scope_locked()}
                              </p>
                            </div>
                          </div>
                        </div>
                      {:else}
                        <!-- Scope Type Selection -->
                        <fieldset>
                          <legend
                            id="scope-type-label"
                            class="text-default mb-3 block text-sm font-semibold tracking-wide"
                            >{m.api_keys_scope()}</legend
                          >
                          <div
                            class="grid grid-cols-2 gap-3 lg:grid-cols-4"
                            role="group"
                            aria-labelledby="scope-type-label"
                          >
                            {#each [{ value: "tenant", label: m.api_keys_scope_tenant(), icon: Building2, desc: m.api_keys_scope_tenant_desc() }, { value: "space", label: m.api_keys_scope_space(), icon: Building2, desc: m.api_keys_scope_space_desc() }, { value: "assistant", label: m.api_keys_scope_assistant(), icon: MessageSquare, desc: m.api_keys_scope_assistant_desc() }, { value: "app", label: m.api_keys_scope_app(), icon: AppWindow, desc: m.api_keys_scope_app_desc() }] as opt (opt.value)}
                              {@const isSelected = scopeType === opt.value}
                              {@const ScopeIcon = opt.icon}
                              <button
                                type="button"
                                onclick={() => (scopeType = opt.value as ApiKeyScopeType)}
                                aria-pressed={isSelected}
                                class="focus-visible:ring-accent-default flex flex-col items-center gap-2 rounded-xl border-2 p-4 transition-all duration-200 ease-out focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2
                                   {isSelected
                                  ? 'border-accent-default bg-accent-default/10 shadow-accent-default/20 dark:shadow-accent-default/10 shadow-md'
                                  : 'border-default bg-primary hover:border-dimmer hover:bg-subtle/50'}"
                              >
                                <div
                                  class="flex h-10 w-10 items-center justify-center rounded-lg transition-all duration-200 ease-out
                                     {isSelected
                                    ? 'bg-accent-default shadow-accent-default/30 text-white shadow-sm'
                                    : 'bg-subtle text-muted'}"
                                >
                                  <ScopeIcon class="h-5 w-5" />
                                </div>
                                <div class="text-center">
                                  <p
                                    class="text-sm font-semibold tracking-wide {isSelected
                                      ? 'text-accent-default'
                                      : 'text-default'}"
                                  >
                                    {opt.label}
                                  </p>
                                  <p class="text-muted text-[11px]">{opt.desc}</p>
                                </div>
                              </button>
                            {/each}
                          </div>
                        </fieldset>

                        <!-- Resource Selector -->
                        {#if scopeType !== "tenant"}
                          <div class="border-default bg-subtle rounded-xl border p-5">
                            {#if loadingResources}
                              <!-- Skeleton loading state -->
                              <div class="space-y-3">
                                <div class="flex items-center gap-3">
                                  <div class="bg-default/50 h-4 w-4 animate-pulse rounded"></div>
                                  <div class="bg-default/50 h-4 w-24 animate-pulse rounded"></div>
                                </div>
                                {#each [1, 2, 3] as _, i (i)}
                                  <div
                                    class="border-default bg-primary flex items-center gap-3 rounded-lg border p-3"
                                  >
                                    <div
                                      class="bg-default/50 h-8 w-8 animate-pulse rounded-lg"
                                    ></div>
                                    <div class="flex-1 space-y-2">
                                      <div
                                        class="bg-default/50 h-4 w-32 animate-pulse rounded"
                                      ></div>
                                      <div
                                        class="bg-default/30 h-3 w-20 animate-pulse rounded"
                                      ></div>
                                    </div>
                                    <div
                                      class="bg-default/50 h-4 w-4 animate-pulse rounded-full"
                                    ></div>
                                  </div>
                                {/each}
                              </div>
                            {:else}
                              <ScopeResourceSelector
                                {scopeType}
                                bind:value={scopeId}
                                {spaces}
                                assistants={assistantOptions}
                                apps={appOptions}
                              />
                              <div class="border-default mt-4 border-t pt-4">
                                <button
                                  type="button"
                                  class="text-muted hover:text-secondary mb-2 flex items-center gap-2 text-xs transition-colors"
                                >
                                  <Info class="h-3.5 w-3.5" />
                                  {m.api_keys_enter_id_manually({ scopeType })}
                                </button>
                                <Input
                                  bind:value={manualScopeId}
                                  placeholder={m.api_keys_enter_uuid()}
                                  class="font-mono text-sm"
                                />
                              </div>
                            {/if}
                          </div>
                        {/if}
                      {/if}

                      <!-- Simple Permission Level -->
                      <fieldset>
                        <legend
                          id="permission-level-label"
                          class="text-default mb-3 block text-sm font-semibold tracking-wide"
                          >{m.api_keys_permission_level()}</legend
                        >
                        <div
                          class="grid gap-3 sm:grid-cols-3"
                          role="radiogroup"
                          aria-labelledby="permission-level-label"
                        >
                          {#each [{ value: "read", label: m.api_keys_permission_read(), icon: Eye, desc: m.api_keys_permission_read_desc() }, { value: "write", label: m.api_keys_permission_write(), icon: Pencil, desc: m.api_keys_permission_write_desc() }, { value: "admin", label: m.api_keys_permission_admin(), icon: ShieldCheck, desc: m.api_keys_permission_admin_desc() }] as opt (opt.value)}
                            {@const isSelected = permission === opt.value}
                            {@const isDisabled = keyType === "pk_" && opt.value !== "read"}
                            {@const PermIcon = opt.icon}
                            {@const levelClasses =
                              opt.value === "read"
                                ? isSelected
                                  ? "border-accent-default bg-accent-default/10"
                                  : "border-default bg-primary hover:border-dimmer"
                                : opt.value === "write"
                                  ? isSelected
                                    ? "border-warning-default bg-warning-default/10"
                                    : "border-default bg-primary hover:border-dimmer"
                                  : isSelected
                                    ? "border-negative-default bg-negative-default/10"
                                    : "border-default bg-primary hover:border-dimmer"}
                            {@const iconClasses =
                              opt.value === "read"
                                ? isSelected
                                  ? "bg-accent-default text-on-fill"
                                  : "bg-accent-default/15 text-accent-default"
                                : opt.value === "write"
                                  ? isSelected
                                    ? "bg-warning-default text-on-fill"
                                    : "bg-warning-default/15 text-warning-stronger"
                                  : isSelected
                                    ? "bg-negative-default text-on-fill"
                                    : "bg-negative-default/15 text-negative-stronger"}
                            {@const checkBgClass =
                              opt.value === "read"
                                ? "bg-accent-default shadow-accent-default/30"
                                : opt.value === "write"
                                  ? "bg-warning-default shadow-warning-default/30"
                                  : "bg-negative-default shadow-negative-default/30"}
                            <button
                              type="button"
                              role="radio"
                              aria-checked={isSelected}
                              onclick={() =>
                                !isDisabled && (permission = opt.value as ApiKeyPermission)}
                              disabled={isDisabled}
                              class="focus-visible:ring-accent-default relative rounded-xl border-2 p-4 text-left transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 {levelClasses}
                                   {isDisabled ? 'cursor-not-allowed' : ''}"
                            >
                              <div class="flex items-center gap-3 {isDisabled ? 'opacity-50' : ''}">
                                <div
                                  class="flex h-10 w-10 items-center justify-center rounded-lg transition-colors {iconClasses}"
                                >
                                  <PermIcon class="h-5 w-5" />
                                </div>
                                <div>
                                  <p class="text-default font-semibold tracking-wide">
                                    {opt.label}
                                  </p>
                                  <p class="text-muted text-xs">{opt.desc}</p>
                                </div>
                              </div>
                              {#if isSelected}
                                <div class="absolute -top-1.5 -right-1.5">
                                  <div
                                    class="flex h-5 w-5 items-center justify-center rounded-full shadow-lg {checkBgClass}"
                                  >
                                    <Check class="text-on-fill h-3 w-3" strokeWidth={3} />
                                  </div>
                                </div>
                              {/if}
                              {#if isDisabled}
                                <p class="text-warning-stronger mt-2 text-xs font-medium">
                                  {m.api_keys_not_available_public()}
                                </p>
                              {/if}
                            </button>
                          {/each}
                        </div>
                      </fieldset>

                      <!-- Contextual capability summary -->
                      <div class="border-default bg-subtle/50 rounded-xl border p-4">
                        <p class="text-muted mb-3 text-xs font-semibold tracking-wider uppercase">
                          {m.api_keys_capability_summary_title()}
                        </p>
                        <div class="space-y-2">
                          {#if permission === "read"}
                            <div class="flex items-center gap-2.5">
                              <div
                                class="bg-positive-default/15 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                              >
                                <Check class="text-positive-stronger h-3 w-3" strokeWidth={3} />
                              </div>
                              <span class="text-default text-sm"
                                >{m.api_keys_capability_read_resources()}</span
                              >
                            </div>
                            <div class="flex items-center gap-2.5">
                              <div
                                class="bg-negative-default/10 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                              >
                                <Ban class="text-negative-stronger h-3 w-3" strokeWidth={2.5} />
                              </div>
                              <span class="text-muted text-sm"
                                >{m.api_keys_capability_no_create()}</span
                              >
                            </div>
                            <div class="flex items-center gap-2.5">
                              <div
                                class="bg-negative-default/10 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                              >
                                <Ban class="text-negative-stronger h-3 w-3" strokeWidth={2.5} />
                              </div>
                              <span class="text-muted text-sm"
                                >{m.api_keys_capability_no_space_settings()}</span
                              >
                            </div>
                          {:else if permission === "write"}
                            <div class="flex items-center gap-2.5">
                              <div
                                class="bg-positive-default/15 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                              >
                                <Check class="text-positive-stronger h-3 w-3" strokeWidth={3} />
                              </div>
                              <span class="text-default text-sm"
                                >{m.api_keys_capability_read_resources()}</span
                              >
                            </div>
                            <div class="flex items-center gap-2.5">
                              <div
                                class="bg-positive-default/15 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                              >
                                <Check class="text-positive-stronger h-3 w-3" strokeWidth={3} />
                              </div>
                              <span class="text-default text-sm"
                                >{m.api_keys_capability_write_resources()}</span
                              >
                            </div>
                            <div class="flex items-center gap-2.5">
                              <div
                                class="bg-negative-default/10 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                              >
                                <Ban class="text-negative-stronger h-3 w-3" strokeWidth={2.5} />
                              </div>
                              <span class="text-muted text-sm"
                                >{m.api_keys_capability_no_space_settings()}</span
                              >
                            </div>
                          {:else if permission === "admin"}
                            <div class="flex items-center gap-2.5">
                              <div
                                class="bg-positive-default/15 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                              >
                                <Check class="text-positive-stronger h-3 w-3" strokeWidth={3} />
                              </div>
                              <span class="text-default text-sm"
                                >{m.api_keys_capability_read_resources()}</span
                              >
                            </div>
                            <div class="flex items-center gap-2.5">
                              <div
                                class="bg-positive-default/15 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                              >
                                <Check class="text-positive-stronger h-3 w-3" strokeWidth={3} />
                              </div>
                              <span class="text-default text-sm"
                                >{m.api_keys_capability_write_resources()}</span
                              >
                            </div>
                            <div class="flex items-center gap-2.5">
                              <div
                                class="bg-positive-default/15 flex h-5 w-5 shrink-0 items-center justify-center rounded-full"
                              >
                                <Check class="text-positive-stronger h-3 w-3" strokeWidth={3} />
                              </div>
                              <span class="text-default text-sm"
                                >{m.api_keys_capability_admin_space()}</span
                              >
                            </div>
                          {/if}

                          <div class="border-default mt-2 border-t pt-2">
                            <div class="flex items-center gap-2.5">
                              <div
                                class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full {ownership ===
                                'service'
                                  ? 'bg-accent-default/15'
                                  : 'bg-tertiary'}"
                              >
                                <Link2
                                  class="h-3 w-3 {ownership === 'service'
                                    ? 'text-accent-default'
                                    : 'text-muted'}"
                                  strokeWidth={2.5}
                                />
                              </div>
                              <span
                                class="text-sm {ownership === 'service'
                                  ? 'text-default'
                                  : 'text-muted'}"
                              >
                                {ownership === "service"
                                  ? m.api_keys_capability_service_lifecycle()
                                  : m.api_keys_capability_user_lifecycle()}
                              </span>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  {:else}
                    <!-- Fine-grained Mode (HuggingFace style) -->
                    <div class="space-y-5">
                      <!-- Quick actions -->
                      <div
                        class="border-default bg-secondary/30 flex items-center justify-between rounded-lg border px-4 py-3"
                      >
                        <div class="flex items-center gap-3">
                          <span class="text-muted text-sm">{m.api_keys_quick_set_all()}</span>
                          <div class="flex gap-1">
                            {#each ["none", "read", "write", "admin"] as level (level)}
                              {@const allowed = isLevelAllowed(level as ResourcePermission)}
                              <button
                                type="button"
                                onclick={() => setAllPermissions(level as ResourcePermission)}
                                disabled={!allowed}
                                class="focus:ring-accent-default/30 rounded-md border px-3 py-1.5 text-xs font-medium transition-all hover:shadow-sm focus:ring-2 focus:outline-none {getLevelClasses(
                                  level as ResourcePermission,
                                  false
                                )} {!allowed ? 'cursor-not-allowed opacity-40' : ''}"
                              >
                                {getLevelLabel(level as ResourcePermission)}
                              </button>
                            {/each}
                          </div>
                        </div>
                        <span class="text-muted text-xs">
                          {m.api_keys_of_enabled({ count: activeResourceCount })}
                        </span>
                      </div>

                      <!-- Two-column permission grid - responsive at md breakpoint -->
                      <div class="grid gap-3 md:grid-cols-2">
                        <!-- Assistants -->
                        <div class="border-default bg-primary overflow-hidden rounded-xl border">
                          <div
                            class="from-subtle to-primary/50 border-default/60 border-b bg-gradient-to-b px-5 py-4"
                          >
                            <div class="flex items-center justify-between">
                              <div class="flex items-center gap-3">
                                <div
                                  class="bg-primary border-default/80 flex h-9 w-9 items-center justify-center rounded-lg border shadow-sm"
                                >
                                  <MessageSquare class="text-secondary h-5 w-5" />
                                </div>
                                <div>
                                  <h4 class="text-default text-sm font-semibold">
                                    {m.api_keys_resource_assistants()}
                                  </h4>
                                  <p class="text-muted text-xs">
                                    {m.api_keys_resource_assistants_desc()}
                                  </p>
                                </div>
                              </div>
                              <span
                                class="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold transition-all duration-200 {getLevelBadgeClasses(
                                  assistantsPermission
                                )}"
                              >
                                {getLevelLabel(assistantsPermission)}
                              </span>
                            </div>
                          </div>
                          <div class="px-5 py-4">
                            <div class="flex gap-2">
                              {#each ["none", "read", "write", "admin"] as level (level)}
                                {@const allowed = isLevelAllowed(level as ResourcePermission)}
                                <button
                                  type="button"
                                  onclick={() =>
                                    (assistantsPermission = level as ResourcePermission)}
                                  disabled={!allowed}
                                  class="focus:ring-accent-default/30 flex-1 rounded-lg border-2 px-3 py-2 text-xs font-medium transition-all focus:ring-2 focus:outline-none {getLevelClasses(
                                    level as ResourcePermission,
                                    assistantsPermission === level
                                  )} {!allowed ? 'cursor-not-allowed opacity-40' : ''}"
                                >
                                  {getLevelLabel(level as ResourcePermission)}
                                </button>
                              {/each}
                            </div>
                          </div>
                        </div>

                        <!-- Apps -->
                        <div
                          class="border-default bg-primary permission-card-enter overflow-hidden rounded-xl border"
                        >
                          <div
                            class="from-subtle to-primary/50 border-default/60 border-b bg-gradient-to-b px-5 py-4"
                          >
                            <div class="flex items-center justify-between">
                              <div class="flex items-center gap-3">
                                <div
                                  class="bg-primary border-default/80 flex h-9 w-9 items-center justify-center rounded-lg border shadow-sm"
                                >
                                  <AppWindow class="text-secondary h-5 w-5" />
                                </div>
                                <div>
                                  <h4 class="text-default text-sm font-semibold">
                                    {m.api_keys_resource_applications()}
                                  </h4>
                                  <p class="text-muted text-xs">
                                    {m.api_keys_resource_applications_desc()}
                                  </p>
                                </div>
                              </div>
                              <span
                                class="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold transition-all duration-200 {getLevelBadgeClasses(
                                  appsPermission
                                )}"
                              >
                                {getLevelLabel(appsPermission)}
                              </span>
                            </div>
                          </div>
                          <div class="px-5 py-4">
                            <div class="flex gap-2">
                              {#each ["none", "read", "write", "admin"] as level (level)}
                                {@const allowed = isLevelAllowed(level as ResourcePermission)}
                                <button
                                  type="button"
                                  onclick={() => (appsPermission = level as ResourcePermission)}
                                  disabled={!allowed}
                                  class="focus:ring-accent-default/30 flex-1 rounded-lg border-2 px-3 py-2 text-xs font-medium transition-all focus:ring-2 focus:outline-none {getLevelClasses(
                                    level as ResourcePermission,
                                    appsPermission === level
                                  )} {!allowed ? 'cursor-not-allowed opacity-40' : ''}"
                                >
                                  {getLevelLabel(level as ResourcePermission)}
                                </button>
                              {/each}
                            </div>
                          </div>
                        </div>

                        <!-- Spaces -->
                        <div
                          class="border-default bg-primary permission-card-enter overflow-hidden rounded-xl border"
                        >
                          <div
                            class="from-subtle to-primary/50 border-default/60 border-b bg-gradient-to-b px-5 py-4"
                          >
                            <div class="flex items-center justify-between">
                              <div class="flex items-center gap-3">
                                <div
                                  class="bg-primary border-default/80 flex h-9 w-9 items-center justify-center rounded-lg border shadow-sm"
                                >
                                  <Building2 class="text-secondary h-5 w-5" />
                                </div>
                                <div>
                                  <h4 class="text-default text-sm font-semibold">
                                    {m.api_keys_resource_spaces()}
                                  </h4>
                                  <p class="text-muted text-xs">
                                    {m.api_keys_resource_spaces_desc()}
                                  </p>
                                </div>
                              </div>
                              <span
                                class="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold transition-all duration-200 {getLevelBadgeClasses(
                                  spacesPermission
                                )}"
                              >
                                {getLevelLabel(spacesPermission)}
                              </span>
                            </div>
                          </div>
                          <div class="px-5 py-4">
                            <div class="flex gap-2">
                              {#each ["none", "read", "write", "admin"] as level (level)}
                                {@const allowed = isLevelAllowed(level as ResourcePermission)}
                                <button
                                  type="button"
                                  onclick={() => (spacesPermission = level as ResourcePermission)}
                                  disabled={!allowed}
                                  class="focus:ring-accent-default/30 flex-1 rounded-lg border-2 px-3 py-2 text-xs font-medium transition-all focus:ring-2 focus:outline-none {getLevelClasses(
                                    level as ResourcePermission,
                                    spacesPermission === level
                                  )} {!allowed ? 'cursor-not-allowed opacity-40' : ''}"
                                >
                                  {getLevelLabel(level as ResourcePermission)}
                                </button>
                              {/each}
                            </div>
                          </div>
                        </div>

                        <!-- Knowledge -->
                        <div
                          class="border-default bg-primary permission-card-enter overflow-hidden rounded-xl border"
                        >
                          <div
                            class="from-subtle to-primary/50 border-default/60 border-b bg-gradient-to-b px-5 py-4"
                          >
                            <div class="flex items-center justify-between">
                              <div class="flex items-center gap-3">
                                <div
                                  class="bg-primary border-default/80 flex h-9 w-9 items-center justify-center rounded-lg border shadow-sm"
                                >
                                  <Sparkles class="text-secondary h-5 w-5" />
                                </div>
                                <div>
                                  <h4 class="text-default text-sm font-semibold">
                                    {m.api_keys_resource_knowledge()}
                                  </h4>
                                  <p class="text-muted text-xs">
                                    {m.api_keys_resource_knowledge_desc()}
                                  </p>
                                </div>
                              </div>
                              <span
                                class="inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold transition-all duration-200 {getLevelBadgeClasses(
                                  knowledgePermission
                                )}"
                              >
                                {getLevelLabel(knowledgePermission)}
                              </span>
                            </div>
                          </div>
                          <div class="px-5 py-4">
                            <div class="flex gap-2">
                              {#each ["none", "read", "write", "admin"] as level (level)}
                                {@const allowed = isLevelAllowed(level as ResourcePermission)}
                                <button
                                  type="button"
                                  onclick={() =>
                                    (knowledgePermission = level as ResourcePermission)}
                                  disabled={!allowed}
                                  class="focus:ring-accent-default/30 flex-1 rounded-lg border-2 px-3 py-2 text-xs font-medium transition-all focus:ring-2 focus:outline-none {getLevelClasses(
                                    level as ResourcePermission,
                                    knowledgePermission === level
                                  )} {!allowed ? 'cursor-not-allowed opacity-40' : ''}"
                                >
                                  {getLevelLabel(level as ResourcePermission)}
                                </button>
                              {/each}
                            </div>
                          </div>
                        </div>
                      </div>

                      <!-- Info note -->
                      <div
                        class="border-accent-default/30 bg-accent-default/5 flex items-start gap-3 rounded-lg border px-4 py-3"
                      >
                        <Info class="text-accent-default mt-0.5 h-4 w-4 flex-shrink-0" />
                        <p class="text-accent-default text-xs leading-relaxed">
                          <!-- eslint-disable-next-line svelte/no-at-html-tags -- localized info is trusted i18n content -->
                          {@html m.api_keys_fine_grained_info()}
                        </p>
                      </div>
                    </div>
                  {/if}
                </div>
              {:else if currentStep === 3}
                <!-- Step 3: Security Settings -->
                <div class="space-y-6">
                  <h3 class="sr-only">{m.api_keys_step_security_sr()}</h3>
                  {#if keyType === "pk_"}
                    <TagInput
                      type="origin"
                      bind:value={allowedOrigins}
                      label={m.api_keys_allowed_origins()}
                      description={m.api_keys_allowed_origins_desc()}
                      placeholder="https://example.com"
                      required
                    />
                  {/if}

                  {#if keyType === "sk_"}
                    <TagInput
                      type="ip"
                      bind:value={allowedIps}
                      label={m.api_keys_allowed_ips()}
                      description={m.api_keys_allowed_ips_desc()}
                      placeholder="192.168.1.0/24"
                    />
                  {/if}

                  <ExpirationPicker
                    bind:value={expiresAt}
                    maxDays={maxExpirationDays}
                    {requireExpiration}
                  />

                  <div>
                    <label
                      for="api-key-rate-limit"
                      class="text-default mb-2 block text-sm font-semibold tracking-wide"
                    >
                      {m.api_keys_rate_limit()}
                    </label>
                    <Input
                      id="api-key-rate-limit"
                      bind:value={rateLimit}
                      placeholder={m.api_keys_rate_limit_placeholder()}
                      type="number"
                      min="1"
                      max={maxRateLimit ?? undefined}
                      class="h-11"
                    />
                    <p class="text-muted mt-2 text-xs">
                      {m.api_keys_rate_limit_help()}
                    </p>
                    {#if maxRateLimit != null}
                      <p class="text-muted mt-1 text-xs">
                        {m.api_keys_rate_limit_max({ max: maxRateLimit })}
                      </p>
                    {/if}
                  </div>
                </div>
              {/if}
            </div>
          {/key}
        </div>
      </div>

      <!-- Footer -->
      <div
        class="border-default bg-subtle flex flex-shrink-0 flex-wrap items-center justify-between gap-3 rounded-b-2xl border-t px-6 py-4"
      >
        <div class="flex-shrink-0">
          {#if currentStep > 1 && currentStep <= totalSteps}
            <Button variant="ghost" onclick={prevStep}>
              <ChevronLeft />
              {m.api_keys_back()}
            </Button>
          {/if}
        </div>

        <div class="flex flex-wrap items-center gap-2 sm:gap-3">
          {#if currentStep <= totalSteps}
            <Button
              variant="outline"
              onclick={() => {
                showDialog = false;
                resetForm();
              }}
            >
              {m.cancel()}
            </Button>
          {/if}

          {#if currentStep < totalSteps}
            <Button variant="default" onclick={nextStep} class="min-w-[80px] sm:min-w-[100px]">
              {m.api_keys_next()}
              <ChevronRight />
            </Button>
          {:else if currentStep === totalSteps}
            <Button
              variant="default"
              onclick={createKey}
              disabled={isSubmitting}
              class="min-w-[100px] sm:min-w-[140px] {isSubmitting ? 'submit-pulse' : ''}"
            >
              {#if isSubmitting}
                <div
                  class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
                  aria-hidden="true"
                ></div>
                <span class="hidden sm:inline">{m.api_keys_creating()}</span>
              {:else}
                <Key />
                <span class="hidden sm:inline">{m.api_keys_create()}</span>
                <span class="sm:hidden">{m.api_keys_create_short()}</span>
              {/if}
            </Button>
          {/if}
        </div>
      </div>
    {:else}
      <!-- Step 4: Secret reveal (shown after successful creation) -->
      <div class="flex-1 overflow-y-auto px-6 pt-8 pb-6">
        <div class="mx-auto max-w-lg">
          <!-- Success header -->
          <div
            class="flex flex-col items-center text-center"
            in:fly={{ y: 12, duration: 350, easing: cubicOut }}
          >
            <div class="relative">
              <div
                class="bg-positive-default/10 secret-ring-pulse absolute -inset-2 rounded-full"
              ></div>
              <div
                class="bg-positive-default/15 ring-positive-default/10 relative flex h-14 w-14 items-center justify-center rounded-full ring-4"
              >
                <CheckCircle2 class="text-positive-stronger h-7 w-7" strokeWidth={2.5} />
              </div>
            </div>

            <h3 class="text-default mt-4 text-lg font-bold tracking-tight">
              {m.api_keys_created_title()}
            </h3>

            {#if createdResponse}
              <p class="text-muted mt-1 text-sm">
                <span class="text-default font-medium">{createdResponse.api_key.name}</span>
                <span class="text-tertiary mx-1.5">&middot;</span>
                <span class="text-tertiary font-mono text-xs"
                  >{createdResponse.api_key.key_prefix}...{createdResponse.api_key.key_suffix}</span
                >
              </p>
            {/if}
          </div>

          <!-- Warning banner -->
          <div class="mt-5" in:fly={{ y: 10, duration: 300, delay: 100, easing: cubicOut }}>
            <Alert.Root class="border-caution/40 bg-caution/8 dark:bg-caution/12">
              <AlertCircle class="text-caution" />
              <Alert.Title class="text-caution">{m.api_keys_important()}</Alert.Title>
              <Alert.Description>{m.api_keys_copy_warning()}</Alert.Description>
            </Alert.Root>
          </div>

          <!-- Secret display -->
          <div class="mt-5" in:fly={{ y: 10, duration: 300, delay: 160, easing: cubicOut }}>
            <p
              id="created-secret-label"
              class="text-muted mb-2 text-xs font-semibold tracking-wider uppercase"
            >
              {m.api_keys_your_new_key()}
            </p>
            <div class="border-default bg-subtle overflow-hidden rounded-xl border">
              <pre
                aria-labelledby="created-secret-label"
                class="text-default overflow-x-auto px-4 py-3.5 font-mono text-[13px] leading-relaxed break-all whitespace-pre-wrap select-all">{createdSecret}</pre>
            </div>

            <div class="mt-3 flex items-center gap-3">
              <Button
                variant={secretCopied ? "outline" : "default"}
                onclick={copySecret}
                aria-label={m.api_keys_copy_to_clipboard()}
              >
                {#if secretCopied}
                  <Check class="text-positive-stronger" />
                  {m.api_keys_copied()}
                {:else}
                  <Copy />
                  {m.api_keys_copy_to_clipboard()}
                {/if}
              </Button>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer for success step -->
      <div
        class="border-default bg-subtle flex flex-shrink-0 items-center justify-end gap-3 rounded-b-2xl border-t px-6 py-4"
      >
        <Button variant="default" onclick={finishAndClose}>
          <Check />
          {m.done()}
        </Button>
      </div>
    {/if}
  </Dialog.Content>
</Dialog.Root>

<style>
  /* Step indicator bounce animation */
  @keyframes step-bounce {
    0%,
    100% {
      transform: scale(1);
    }
    50% {
      transform: scale(1.08);
    }
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

  :global(.permission-card-enter:nth-child(1)) {
    animation-delay: 0ms;
  }
  :global(.permission-card-enter:nth-child(2)) {
    animation-delay: 50ms;
  }
  :global(.permission-card-enter:nth-child(3)) {
    animation-delay: 100ms;
  }
  :global(.permission-card-enter:nth-child(4)) {
    animation-delay: 150ms;
  }

  /* Submit button pulse animation when loading */
  @keyframes submit-pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.85;
    }
  }

  :global(.submit-pulse) {
    animation: submit-pulse 1.5s ease-in-out infinite;
  }

  /* Secret reveal icon ring pulse */
  @keyframes ring-pulse {
    0% {
      transform: scale(1);
      opacity: 0.6;
    }
    50% {
      transform: scale(1.15);
      opacity: 0;
    }
    100% {
      transform: scale(1);
      opacity: 0;
    }
  }

  :global(.secret-ring-pulse) {
    animation: ring-pulse 1.8s ease-out 0.3s;
  }
</style>
