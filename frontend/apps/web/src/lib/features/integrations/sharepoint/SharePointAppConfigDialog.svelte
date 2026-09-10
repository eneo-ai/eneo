<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type { Writable } from "svelte/store";
  import type { components } from "@eneo/eneo-js";
  import {
    AlertTriangle,
    CheckCircle2,
    FlaskConical,
    LoaderCircle,
    RefreshCw
  } from "lucide-svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage, toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import SharePointFixtureBanner from "./SharePointFixtureBanner.svelte";
  import {
    createSharePointSetupFixtureConfig,
    isSharePointSetupFixtureScenario,
    SHAREPOINT_SETUP_FIXTURE_TEST_ERROR,
    sharePointFixtureDelay,
    type SharePointSetupFixtureScenario
  } from "./fixtureMode";

  type TenantSharePointAppPublic = components["schemas"]["TenantSharePointAppPublic"];
  type TenantSharePointAppCreate = components["schemas"]["TenantSharePointAppCreate"];
  type TenantAppTestResult = components["schemas"]["TenantAppTestResult"];
  type AuthMethod = "tenant_app" | "service_account";

  let {
    openController,
    onDeleteRequested,
    fixtureScenario: fixtureScenarioOverride
  }: {
    openController: Writable<boolean>;
    onDeleteRequested?: () => void;
    fixtureScenario?: SharePointSetupFixtureScenario;
  } = $props();

  const isFixtureSession = $derived(fixtureScenarioOverride !== undefined);

  const eneo = getEneo();

  let dialogOpen = $state(false);
  onMount(() => openController.subscribe((value) => (dialogOpen = value)));
  $effect(() => {
    openController.set(dialogOpen);
  });

  let authMethod = $state<AuthMethod>("service_account");
  let clientId = $state("");
  let clientSecret = $state("");
  let tenantDomain = $state("");
  let existingConfig = $state<TenantSharePointAppPublic | null>(null);
  let configLoadFailed = $state(false);
  let testResult = $state<TenantAppTestResult | null>(null);
  let isUpdatingSecret = $state(false);
  let newClientSecret = $state("");
  let activeFixtureScenario = $state<SharePointSetupFixtureScenario>(
    untrack(() => fixtureScenarioOverride ?? "fresh")
  );

  let credentialsComplete = $derived(
    clientId.trim().length > 0 && clientSecret.trim().length > 0 && tenantDomain.trim().length > 0
  );

  function getSetupScenarioLabel(scenario: SharePointSetupFixtureScenario): string {
    switch (scenario) {
      case "fresh":
        return m.sharepoint_setup_fixture_scenario_fresh();
      case "configured":
        return m.sharepoint_setup_fixture_scenario_configured();
      case "connection_error":
        return m.sharepoint_setup_fixture_scenario_connection_error();
    }
  }

  function applyExistingConfig(config: TenantSharePointAppPublic) {
    existingConfig = config;
    clientId = config.client_id;
    tenantDomain = config.tenant_domain;
    authMethod = config.auth_method === "service_account" ? "service_account" : "tenant_app";
  }

  function resetFormState() {
    existingConfig = null;
    configLoadFailed = false;
    clientId = "";
    clientSecret = "";
    tenantDomain = "";
    testResult = null;
    authMethod = "service_account";
    isUpdatingSecret = false;
    newClientSecret = "";
  }

  function changeSetupScenario(value: string) {
    if (!isSharePointSetupFixtureScenario(value) || value === activeFixtureScenario) return;
    activeFixtureScenario = value;
    resetFormState();
    loadConfig();
  }

  function fixtureConnectionFailure(): TenantAppTestResult {
    return { success: false, error_message: SHAREPOINT_SETUP_FIXTURE_TEST_ERROR };
  }

  const loadConfig = createAsyncState(async () => {
    configLoadFailed = false;

    if (isFixtureSession) {
      await sharePointFixtureDelay(300);
      if (activeFixtureScenario === "configured") {
        applyExistingConfig(createSharePointSetupFixtureConfig({ authMethod: "service_account" }));
      }
      return;
    }

    try {
      const data = await eneo.client.fetch("/api/v1/admin/sharepoint/app", { method: "get" });
      if (data) applyExistingConfig(data);
    } catch (error) {
      configLoadFailed = true;
      toastError(error, m.sharepoint_config_load_error());
    }
  });

  function buildCredentialsPayload(): TenantSharePointAppCreate {
    return {
      client_id: clientId.trim(),
      client_secret: clientSecret,
      tenant_domain: tenantDomain.trim()
    };
  }

  const testCredentials = createAsyncState(async () => {
    if (!credentialsComplete) return;
    testResult = null;

    if (isFixtureSession) {
      await sharePointFixtureDelay();
      testResult =
        activeFixtureScenario === "connection_error"
          ? fixtureConnectionFailure()
          : { success: true, details: m.sharepoint_setup_fixture_test_success_details() };
      return;
    }

    try {
      testResult = await eneo.client.fetch("/api/v1/admin/sharepoint/app/test", {
        method: "post",
        requestBody: { "application/json": buildCredentialsPayload() }
      });
    } catch (error) {
      toastError(error);
      testResult = { success: false, error_message: getErrorMessage(error) };
    }
  });

  const saveConfig = createAsyncState(async () => {
    if (!credentialsComplete) return;

    if (isFixtureSession) {
      await sharePointFixtureDelay();
      if (activeFixtureScenario === "connection_error") {
        testResult = fixtureConnectionFailure();
        toast.error(m.connection_test_failed());
        return;
      }
      applyExistingConfig(
        createSharePointSetupFixtureConfig({
          authMethod: "tenant_app",
          clientId,
          tenantDomain,
          clientSecret
        })
      );
      toast.success(m.sharepoint_fixture_simulated_saved());
      return;
    }

    try {
      existingConfig = await eneo.client.fetch("/api/v1/admin/sharepoint/app", {
        method: "post",
        requestBody: { "application/json": buildCredentialsPayload() }
      });
      toast.success(m.sharepoint_config_saved());
      dialogOpen = false;
    } catch (error) {
      toastError(error);
    }
  });

  const updateSecret = createAsyncState(async () => {
    if (!existingConfig || newClientSecret.trim().length === 0) return;

    if (isFixtureSession) {
      await sharePointFixtureDelay();
      existingConfig = {
        ...existingConfig,
        client_secret_masked: `••••••••${newClientSecret.slice(-3)}`
      };
      toast.success(m.sharepoint_fixture_simulated_saved());
      isUpdatingSecret = false;
      newClientSecret = "";
      return;
    }

    try {
      existingConfig = await eneo.client.fetch("/api/v1/admin/sharepoint/app", {
        method: "post",
        requestBody: {
          "application/json": {
            client_id: existingConfig.client_id,
            client_secret: newClientSecret,
            tenant_domain: existingConfig.tenant_domain
          }
        }
      });
      toast.success(m.sharepoint_secret_updated());
      isUpdatingSecret = false;
      newClientSecret = "";
    } catch (error) {
      toastError(error);
    }
  });

  const startServiceAccountOAuth = createAsyncState(async () => {
    if (!credentialsComplete) return;

    if (isFixtureSession) {
      await sharePointFixtureDelay(700);
      if (activeFixtureScenario === "connection_error") {
        testResult = fixtureConnectionFailure();
        toast.error(m.connection_test_failed());
        return;
      }
      applyExistingConfig(
        createSharePointSetupFixtureConfig({
          authMethod: "service_account",
          clientId,
          tenantDomain,
          clientSecret
        })
      );
      toast.success(m.sharepoint_fixture_simulated_saved());
      return;
    }

    try {
      const result = await eneo.client.fetch(
        "/api/v1/admin/sharepoint/service-account/auth/start",
        {
          method: "post",
          requestBody: { "application/json": buildCredentialsPayload() }
        }
      );

      sessionStorage.setItem(
        "sharepoint_service_account_oauth",
        JSON.stringify({ state: result.state })
      );
      window.location.href = result.auth_url;
    } catch (error) {
      toastError(error);
    }
  });

  function requestDelete() {
    dialogOpen = false;
    onDeleteRequested?.();
  }

  $effect(() => {
    if (dialogOpen) loadConfig();
  });

  $effect(() => {
    if (!dialogOpen) {
      resetFormState();
      activeFixtureScenario = fixtureScenarioOverride ?? "fresh";
    }
  });
</script>

<Dialog.Root bind:open={dialogOpen}>
  <Dialog.Content
    class="flex max-h-[calc(100dvh-2rem)] flex-col gap-0 overflow-hidden p-0 sm:max-h-[85dvh] sm:max-w-xl"
    closeLabel={m.close()}
  >
    <Dialog.Header class="shrink-0 border-b px-6 py-4 pr-12">
      <Dialog.Title>
        {isFixtureSession
          ? m.sharepoint_setup_fixture_dialog_title()
          : m.configure_sharepoint_app_title()}
      </Dialog.Title>
      {#if isFixtureSession}
        <Dialog.Description>{m.sharepoint_setup_fixture_dialog_description()}</Dialog.Description>
      {/if}
    </Dialog.Header>

    {#if isFixtureSession}
      <SharePointFixtureBanner
        class="mx-6 mt-3 w-auto shrink-0"
        scenarios={[
          { value: "fresh", label: m.sharepoint_setup_fixture_scenario_fresh() },
          { value: "configured", label: m.sharepoint_setup_fixture_scenario_configured() },
          {
            value: "connection_error",
            label: m.sharepoint_setup_fixture_scenario_connection_error()
          }
        ]}
        value={activeFixtureScenario}
        triggerLabel={getSetupScenarioLabel(activeFixtureScenario)}
        description={m.sharepoint_setup_fixture_banner_description()}
        disabled={loadConfig.isLoading}
        onValueChange={changeSetupScenario}
      />
    {/if}

    <div class="min-h-0 flex-1 overflow-y-auto px-6 py-5">
      {#if loadConfig.isLoading}
        <div
          class="text-muted-foreground flex items-center justify-center gap-2 py-10"
          role="status"
        >
          <LoaderCircle class="size-4 animate-spin" aria-hidden="true" />
          {m.loading_configuration()}
        </div>
      {:else if configLoadFailed}
        <div class="flex flex-col items-center gap-3 py-10 text-center" role="alert">
          <p class="text-destructive text-sm">{m.sharepoint_config_load_error()}</p>
          <Button variant="outline" size="sm" onclick={() => loadConfig()}>
            <RefreshCw aria-hidden="true" />
            {m.retry()}
          </Button>
        </div>
      {:else if existingConfig}
        <div class="flex flex-col gap-4">
          <div class="border-border bg-muted/50 rounded-lg border p-4">
            <h3 class="mb-3 text-sm font-semibold">{m.current_configuration()}</h3>
            <dl class="grid grid-cols-[auto_1fr] items-baseline gap-x-6 gap-y-2 text-sm">
              <dt class="text-muted-foreground">{m.auth_method()}</dt>
              <dd>
                {existingConfig.auth_method === "service_account"
                  ? m.service_account_option()
                  : m.tenant_app_option()}
              </dd>
              <dt class="text-muted-foreground">{m.client_id()}</dt>
              <dd class="truncate font-mono text-xs" title={existingConfig.client_id}>
                {existingConfig.client_id}
              </dd>
              <dt class="text-muted-foreground">{m.secret()}</dt>
              <dd class="font-mono text-xs">{existingConfig.client_secret_masked}</dd>
              <dt class="text-muted-foreground">{m.domain()}</dt>
              <dd class="truncate" title={existingConfig.tenant_domain}>
                {existingConfig.tenant_domain}
              </dd>
              {#if existingConfig.service_account_email}
                <dt class="text-muted-foreground">{m.service_account_email()}</dt>
                <dd class="truncate" title={existingConfig.service_account_email}>
                  {existingConfig.service_account_email}
                </dd>
              {/if}
              <dt class="text-muted-foreground">{m.status()}</dt>
              <dd>
                {#if existingConfig.is_active}
                  <Badge class="bg-positive-dimmer text-positive-stronger border-transparent">
                    {m.active()}
                  </Badge>
                {:else}
                  <Badge variant="destructive">{m.inactive()}</Badge>
                {/if}
              </dd>
            </dl>
          </div>

          {#if isUpdatingSecret}
            <Field.Field>
              <Field.Label for="sharepoint-new-secret">{m.new_client_secret()}</Field.Label>
              <Input
                id="sharepoint-new-secret"
                type="password"
                bind:value={newClientSecret}
                placeholder={m.enter_new_client_secret()}
                autocomplete="off"
                aria-describedby="sharepoint-new-secret-description"
              />
              <Field.Description id="sharepoint-new-secret-description">
                {m.new_client_secret_description()}
              </Field.Description>
            </Field.Field>
          {:else}
            <Alert.Root class="border-caution bg-caution">
              <AlertTriangle class="text-caution!" aria-hidden="true" />
              <Alert.Description>{m.sharepoint_change_auth_warning()}</Alert.Description>
            </Alert.Root>
          {/if}
        </div>
      {:else}
        <div class="flex flex-col gap-5">
          <RadioGroup.Root
            bind:value={() => authMethod, (value) => (authMethod = value as AuthMethod)}
            aria-label={m.choose_auth_method()}
            class="gap-3"
          >
            <p class="text-sm font-medium">{m.choose_auth_method()}</p>

            <Label
              for="sharepoint-auth-service-account"
              class="border-border hover:border-stronger has-[[data-state=checked]]:border-accent-default has-[[data-state=checked]]:bg-accent-dimmer flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors"
            >
              <RadioGroup.Item
                value="service_account"
                id="sharepoint-auth-service-account"
                class="mt-0.5"
              />
              <span class="flex flex-1 flex-col gap-1">
                <span class="flex flex-wrap items-center gap-2 font-medium">
                  {m.service_account_option()}
                  <Badge variant="secondary">{m.recommended()}</Badge>
                </span>
                <span class="text-muted-foreground text-sm font-normal">
                  {m.service_account_description()}
                </span>
              </span>
            </Label>

            <Label
              for="sharepoint-auth-tenant-app"
              class="border-border hover:border-stronger has-[[data-state=checked]]:border-accent-default has-[[data-state=checked]]:bg-accent-dimmer flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors"
            >
              <RadioGroup.Item value="tenant_app" id="sharepoint-auth-tenant-app" class="mt-0.5" />
              <span class="flex flex-1 flex-col gap-1">
                <span class="font-medium">{m.tenant_app_option()}</span>
                <span class="text-muted-foreground text-sm font-normal">
                  {m.tenant_app_description()}
                </span>
              </span>
            </Label>
          </RadioGroup.Root>

          <p class="text-muted-foreground text-sm">
            {m.sharepoint_app_config_description()}
          </p>

          <Field.Field>
            <Field.Label for="sharepoint-client-id">{m.client_id()}</Field.Label>
            <Input
              id="sharepoint-client-id"
              bind:value={clientId}
              required
              placeholder="12345678-1234-1234-1234-123456789012"
              autocomplete="off"
              aria-describedby="sharepoint-client-id-description"
            />
            <Field.Description id="sharepoint-client-id-description">
              {m.client_id_description()}
            </Field.Description>
          </Field.Field>

          <Field.Field>
            <Field.Label for="sharepoint-client-secret">{m.client_secret()}</Field.Label>
            <Input
              id="sharepoint-client-secret"
              type="password"
              bind:value={clientSecret}
              required
              placeholder={m.sharepoint_enter_client_secret()}
              autocomplete="off"
              aria-describedby="sharepoint-client-secret-description"
            />
            <Field.Description id="sharepoint-client-secret-description">
              {m.client_secret_description()}
            </Field.Description>
          </Field.Field>

          <Field.Field>
            <Field.Label for="sharepoint-tenant-domain">{m.tenant_id_or_domain()}</Field.Label>
            <Input
              id="sharepoint-tenant-domain"
              bind:value={tenantDomain}
              required
              placeholder={m.sharepoint_tenant_domain_placeholder()}
              autocomplete="off"
              aria-describedby="sharepoint-tenant-domain-description"
            />
            <Field.Description id="sharepoint-tenant-domain-description">
              {m.tenant_id_or_domain_description()}
            </Field.Description>
          </Field.Field>

          {#if testResult}
            {#if testResult.success}
              <Alert.Root class="border-positive-default/40 bg-positive-default/10" role="status">
                <CheckCircle2 class="text-positive-stronger!" aria-hidden="true" />
                <Alert.Title>{m.connection_successful()}</Alert.Title>
                {#if testResult.details}
                  <Alert.Description>{testResult.details}</Alert.Description>
                {/if}
              </Alert.Root>
            {:else}
              <Alert.Root variant="destructive" role="alert">
                <AlertTriangle aria-hidden="true" />
                <Alert.Title>{m.connection_failed()}</Alert.Title>
                {#if testResult.error_message || testResult.details}
                  <Alert.Description>
                    {testResult.error_message ?? ""}
                    {testResult.details ?? ""}
                  </Alert.Description>
                {/if}
              </Alert.Root>
            {/if}
          {/if}
        </div>
      {/if}
    </div>

    <Dialog.Footer class="mx-0 mb-0 shrink-0 rounded-none border-t px-6 py-4">
      <Button variant="outline" class="w-full sm:w-auto" onclick={() => (dialogOpen = false)}>
        {m.cancel()}
      </Button>

      {#if loadConfig.isLoading || configLoadFailed}
        <!-- Only cancel is meaningful until the config state is known -->
      {:else if existingConfig && isUpdatingSecret}
        <Button
          variant="outline"
          class="w-full sm:w-auto"
          onclick={() => {
            isUpdatingSecret = false;
            newClientSecret = "";
          }}
        >
          {m.back()}
        </Button>
        <Button
          class="w-full sm:w-auto"
          disabled={updateSecret.isLoading || newClientSecret.trim().length === 0}
          onclick={updateSecret}
        >
          {#if updateSecret.isLoading}
            <LoaderCircle class="animate-spin" aria-hidden="true" />
          {/if}
          {updateSecret.isLoading ? m.saving() : m.save()}
        </Button>
      {:else if existingConfig}
        <Button
          variant="outline"
          class="w-full sm:w-auto"
          onclick={() => (isUpdatingSecret = true)}
        >
          {m.update_secret()}
        </Button>
        {#if onDeleteRequested}
          <Button variant="destructive" class="w-full sm:w-auto" onclick={requestDelete}>
            {m.delete_sharepoint_app()}
          </Button>
        {/if}
      {:else if authMethod === "tenant_app"}
        <Button
          variant="outline"
          class="w-full sm:w-auto"
          disabled={testCredentials.isLoading || !credentialsComplete}
          onclick={testCredentials}
        >
          {#if testCredentials.isLoading}
            <LoaderCircle class="animate-spin" aria-hidden="true" />
          {/if}
          {testCredentials.isLoading ? m.testing() : m.test_connection()}
        </Button>
        <Button
          class="w-full sm:w-auto"
          disabled={saveConfig.isLoading || !credentialsComplete}
          onclick={saveConfig}
        >
          {#if saveConfig.isLoading}
            <LoaderCircle class="animate-spin" aria-hidden="true" />
          {:else if isFixtureSession}
            <FlaskConical aria-hidden="true" />
          {/if}
          {#if saveConfig.isLoading}
            {m.saving()}
          {:else if isFixtureSession}
            {m.sharepoint_fixture_simulate_save()}
          {:else}
            {m.save()}
          {/if}
        </Button>
      {:else}
        <Button
          class="w-full sm:w-auto"
          disabled={startServiceAccountOAuth.isLoading || !credentialsComplete}
          onclick={startServiceAccountOAuth}
        >
          {#if startServiceAccountOAuth.isLoading}
            <LoaderCircle class="animate-spin" aria-hidden="true" />
          {:else if isFixtureSession}
            <FlaskConical aria-hidden="true" />
          {/if}
          {#if startServiceAccountOAuth.isLoading}
            {m.redirecting()}
          {:else if isFixtureSession}
            {m.sharepoint_fixture_simulate_sign_in()}
          {:else}
            {m.sign_in_with_microsoft()}
          {/if}
        </Button>
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
