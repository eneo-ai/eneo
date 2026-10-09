<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Connect or edit one speaker identification service. The key is write-only:
  on edit a blank key keeps the saved one, and a moved address needs a new key
  because the backend never sends the stored key to another destination. A
  new service is tested at once and the dialog stays open on it, so a wrong
  key or address can be fixed in place.
-->

<script lang="ts">
  import { tick, untrack } from "svelte";
  import {
    EneoError,
    type SecurityClassification,
    type TranscriptionService,
    type TranscriptionServiceCreate,
    type TranscriptionServiceLastCheck,
    type TranscriptionServiceUpdate
  } from "@eneo/eneo-js";
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Spinner } from "$lib/components/ui/spinner/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { getErrorMessage } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";
  import TranscriptionServiceCheckStatus from "./TranscriptionServiceCheckStatus.svelte";

  type Props = {
    open: boolean;
    /** The saved service to edit; null connects a new one. Read when mounted. */
    service: TranscriptionService | null;
    classifications: SecurityClassification[];
    /** The latest check of the saved settings. */
    check?: TranscriptionServiceLastCheck;
    /** A check of the saved settings is running. */
    checking: boolean;
    /** The owner saves; a rejection keeps the dialog open with the entered values. */
    onCreate: (body: TranscriptionServiceCreate) => Promise<TranscriptionService>;
    onUpdate: (id: string, body: TranscriptionServiceUpdate) => Promise<TranscriptionService>;
    onTest: () => void;
  };

  let {
    open = $bindable(),
    service,
    classifications,
    check,
    checking,
    onCreate,
    onUpdate,
    onTest
  }: Props = $props();

  const uid = $props.id();
  const NONE = "none";

  // The owner mounts the dialog afresh for each opening, so the form starts
  // from the saved settings, or empty, and a cancelled edit is forgotten.
  // Connecting turns the dialog into the editor of the new service.
  const initial = untrack(() => service);
  let saved = $state(initial);
  let connected = $state(false);
  // What was last saved, not what the service reads back: with classification
  // enforcement off the API reads every classification as none.
  let savedClassificationId = $state(initial?.security_classification?.id ?? NONE);
  let name = $state(initial?.name ?? "");
  let address = $state(initial?.endpoint_url ?? "");
  let apiKey = $state("");
  let classificationId = $state(initial?.security_classification?.id ?? NONE);
  let attempted = $state(false);
  let submitting = $state(false);
  let saveFirst = $state(false);
  let nameTaken = $state(false);
  let addressError = $state<string | null>(null);
  let formError = $state<string | null>(null);
  let doneButton = $state<HTMLButtonElement | null>(null);

  const sortedClassifications = $derived(
    [...classifications].sort((a, b) => b.security_level - a.security_level)
  );
  const classificationLabel = $derived(
    classifications.find((classification) => classification.id === classificationId)?.name ??
      m.speaker_service_classification_none()
  );

  // The backend stores an address without its trailing "/" or "/v1", so
  // https://x/ and https://x/v1 are the saved https://x, not a move.
  function endpointBase(url: string): string {
    const base = url.trim().replace(/\/+$/, "");
    return base.endsWith("/v1") ? base.slice(0, -3).replace(/\/+$/, "") : base;
  }

  const addressMoved = $derived(
    saved !== null && endpointBase(address) !== endpointBase(saved.endpoint_url)
  );
  const nameMissing = $derived(!name.trim());
  const addressMissing = $derived(!address.trim());
  const keyMissing = $derived((saved === null || addressMoved) && !apiKey.trim());
  const nameChanged = $derived(saved !== null && name.trim() !== saved.name);
  const classificationChanged = $derived(classificationId !== savedClassificationId);
  const dirty = $derived(
    saved !== null && (nameChanged || addressMoved || apiKey !== "" || classificationChanged)
  );

  const nameInvalid = $derived(nameTaken || (attempted && nameMissing));
  const addressInvalid = $derived(addressError !== null || (attempted && addressMissing));
  const keyInvalid = $derived(attempted && keyMissing);

  function touchesEndpoint(error: EneoError): boolean {
    const errors: unknown = error.response?.details?.errors;
    return (
      Array.isArray(errors) &&
      errors.some(
        (entry) => Array.isArray(entry?.location) && entry.location.includes("endpoint_url")
      )
    );
  }

  // The backend names why an address is refused with a closed code.
  const ENDPOINT_PROBLEMS: Record<string, () => string> = {
    service_endpoint_too_long: m.speaker_service_endpoint_too_long,
    service_endpoint_not_http: m.speaker_service_endpoint_not_http,
    service_endpoint_credentials: m.speaker_service_endpoint_credentials,
    service_endpoint_query: m.speaker_service_endpoint_query,
    service_endpoint_port: m.speaker_service_endpoint_port
  };

  function endpointProblem(error: EneoError): string {
    const errors: unknown = error.response?.details?.errors;
    const type = Array.isArray(errors)
      ? errors.find((entry) => typeof entry?.type === "string" && entry.type in ENDPOINT_PROBLEMS)
          ?.type
      : undefined;
    return type ? ENDPOINT_PROBLEMS[type]() : getErrorMessage(error);
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    attempted = true;
    if (submitting || nameMissing || addressMissing || keyMissing) return;
    submitting = true;
    nameTaken = false;
    addressError = null;
    formError = null;
    const classification = classificationId === NONE ? null : { id: classificationId };
    try {
      if (saved) {
        // Only what the administrator changed: the read shape is not the stored
        // one (with enforcement off a stored classification reads as null), so
        // echoing it back would overwrite what was never touched.
        const updated = await onUpdate(saved.id, {
          ...(nameChanged && { name: name.trim() }),
          ...(classificationChanged && { security_classification: classification }),
          ...(addressMoved && { endpoint_url: address.trim() }),
          ...(apiKey.trim() && { api_key: apiKey.trim() })
        });
        // A service just connected stays open, so the new test is seen too.
        if (!connected) open = false;
        saved = updated;
        savedClassificationId = classificationId;
        apiKey = "";
        attempted = false;
      } else {
        saved = await onCreate({
          name: name.trim(),
          endpoint_url: address.trim(),
          api_key: apiKey.trim(),
          is_enabled: true,
          security_classification: classification
        });
        connected = true;
        savedClassificationId = classificationId;
        apiKey = "";
        attempted = false;
      }
    } catch (error) {
      // The entered values stay; the message goes to the field it is about.
      if (error instanceof EneoError && error.status === 409) {
        nameTaken = true;
      } else if (error instanceof EneoError && error.status === 422 && touchesEndpoint(error)) {
        addressError = endpointProblem(error);
      } else {
        formError = getErrorMessage(error);
      }
    } finally {
      submitting = false;
    }
    // Once connected the connect button is gone; focus the way out, not the
    // first field.
    if (connected && !dirty) {
      await tick();
      doneButton?.focus();
    }
  }

  function test() {
    saveFirst = dirty;
    if (!dirty) onTest();
  }
</script>

<Dialog.Root
  bind:open={
    () => open,
    (value) => {
      if (!submitting) open = value;
    }
  }
>
  <Dialog.Content class={dialogLayout.content("small")}>
    <form class="contents" onsubmit={submit} novalidate>
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>
          {connected && saved
            ? m.speaker_service_dialog_connected_title({ name: saved.name })
            : saved
              ? m.speaker_service_dialog_edit_title({ name: saved.name })
              : m.speaker_service_dialog_create_title()}
        </Dialog.Title>
        <Dialog.Description>{m.speaker_service_dialog_description()}</Dialog.Description>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        {#if formError}
          <Alert.Root variant="destructive">
            <CircleAlert />
            <Alert.Description>{formError}</Alert.Description>
          </Alert.Root>
        {/if}

        <!-- Locked while saving, so nothing typed meanwhile is lost when the save
             answers and the form moves on to the saved settings. -->
        <fieldset class="contents" disabled={submitting}>
          <Field.Group>
            <Field.Field data-invalid={nameInvalid || undefined}>
              <Field.Label for="{uid}-name">{m.name()}</Field.Label>
              <Input
                id="{uid}-name"
                bind:value={name}
                autocomplete="off"
                aria-invalid={nameInvalid}
                aria-describedby={nameInvalid ? `${uid}-name-error` : undefined}
              />
              {#if nameTaken}
                <Field.Error id="{uid}-name-error">{m.speaker_service_name_taken()}</Field.Error>
              {:else if attempted && nameMissing}
                <Field.Error id="{uid}-name-error">{m.speaker_service_name_required()}</Field.Error>
              {/if}
            </Field.Field>

            <Field.Field data-invalid={addressInvalid || undefined}>
              <Field.Label for="{uid}-address">{m.speaker_service_address()}</Field.Label>
              <Input
                id="{uid}-address"
                type="url"
                bind:value={address}
                autocomplete="off"
                spellcheck="false"
                aria-invalid={addressInvalid}
                aria-describedby="{uid}-address-note"
                oninput={() => (addressError = null)}
              />
              {#if addressError}
                <Field.Error id="{uid}-address-note">{addressError}</Field.Error>
              {:else if attempted && addressMissing}
                <Field.Error id="{uid}-address-note"
                  >{m.speaker_service_address_required()}</Field.Error
                >
              {:else}
                <Field.Description id="{uid}-address-note">
                  {m.speaker_service_address_help()}
                </Field.Description>
              {/if}
            </Field.Field>

            <Field.Field data-invalid={keyInvalid || undefined}>
              <Field.Label for="{uid}-key">{m.speaker_service_api_key()}</Field.Label>
              <Input
                id="{uid}-key"
                type="password"
                bind:value={apiKey}
                autocomplete="new-password"
                placeholder={saved && !addressMoved
                  ? m.speaker_service_api_key_saved_placeholder()
                  : undefined}
                aria-invalid={keyInvalid}
                aria-describedby={saved || keyInvalid ? `${uid}-key-note` : undefined}
              />
              {#if keyInvalid}
                <Field.Error id="{uid}-key-note">
                  {addressMoved
                    ? m.speaker_service_api_key_new_address()
                    : m.speaker_service_api_key_required()}
                </Field.Error>
              {:else if addressMoved && keyMissing}
                <!-- Said before submitting, calmly; it turns into an error only on a save attempt. -->
                <Field.Description id="{uid}-key-note">
                  {m.speaker_service_api_key_new_address()}
                </Field.Description>
              {:else if saved}
                <Field.Description id="{uid}-key-note">
                  {m.speaker_service_api_key_edit_help()}
                </Field.Description>
              {/if}
            </Field.Field>

            <Field.Field>
              <Field.Label for="{uid}-classification">
                {m.speaker_service_column_classification()}
              </Field.Label>
              <Select.Root type="single" bind:value={classificationId}>
                <Select.Trigger
                  id="{uid}-classification"
                  class="w-full"
                  aria-describedby="{uid}-classification-help"
                >
                  <span class="truncate">{classificationLabel}</span>
                </Select.Trigger>
                <Select.Content>
                  <Select.Group>
                    <Select.Item value={NONE} label={m.speaker_service_classification_none()}>
                      {m.speaker_service_classification_none()}
                    </Select.Item>
                    {#each sortedClassifications as classification (classification.id)}
                      <Select.Item value={classification.id} label={classification.name}>
                        {classification.name}
                      </Select.Item>
                    {/each}
                  </Select.Group>
                </Select.Content>
              </Select.Root>
              <Field.Description id="{uid}-classification-help">
                {m.speaker_service_classification_help()}
              </Field.Description>
            </Field.Field>
          </Field.Group>
        </fieldset>

        {#if saved}
          {#if saveFirst && dirty}
            <p class="text-muted-foreground text-sm" role="status">
              {m.speaker_service_save_first()}
            </p>
          {:else if checking}
            <!-- The same callout shape as the result, so the dialog keeps its height. -->
            <Alert.Root role="status">
              <Spinner aria-hidden="true" />
              <Alert.Title>{m.speaker_service_testing_connection()}</Alert.Title>
              <Alert.Description>{m.speaker_service_testing_connection_detail()}</Alert.Description>
            </Alert.Root>
          {:else if check}
            <TranscriptionServiceCheckStatus {check} callout />
          {/if}
        {/if}
      </div>

      <Dialog.Footer class={cn(dialogLayout.footer, saved && "sm:justify-between")}>
        {#if saved}
          <Button type="button" variant="outline" disabled={checking || submitting} onclick={test}>
            {#if checking}
              <Spinner data-icon="inline-start" aria-hidden="true" />
            {/if}
            {checking ? m.speaker_service_testing() : m.speaker_service_test()}
          </Button>
        {/if}
        <div class="flex flex-col-reverse gap-2 sm:flex-row">
          {#if saved && !dirty && !submitting}
            <!-- Everything is saved: one way out, nothing to cancel. -->
            <Button type="button" bind:ref={doneButton} onclick={() => (open = false)}>
              {m.done()}
            </Button>
          {:else}
            <Button
              type="button"
              variant="outline"
              disabled={submitting}
              onclick={() => (open = false)}
            >
              {m.cancel()}
            </Button>
            <Button type="submit" disabled={submitting}>
              {#if submitting}
                <Spinner data-icon="inline-start" aria-hidden="true" />
              {/if}
              {submitting ? m.saving() : saved ? m.save() : m.speaker_service_connect_submit()}
            </Button>
          {/if}
        </div>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
