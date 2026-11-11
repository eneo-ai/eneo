<script lang="ts">
  import { tick, untrack } from "svelte";
  import type { ActionResult } from "@sveltejs/kit";
  import { deserialize } from "$app/forms";
  import { beforeNavigate, invalidate } from "$app/navigation";
  import { resolve } from "$app/paths";
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import Copy from "@lucide/svelte/icons/copy";
  import { Settings } from "$lib/components/layout";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { toast } from "$lib/components/toast";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { assignLocation } from "$lib/core/navigation";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { createCopyState } from "$lib/core/helpers/clipboard.svelte";
  import {
    changedFields,
    consequences,
    domainChange,
    draftFromView,
    FEDERATION_FIELDS,
    parseDomains,
    RISKY,
    toFormData,
    validate,
    type Consequence,
    type FederationField,
    type FederationView,
    type FieldProblem
  } from "$lib/features/federation/federationDraft";
  import { m } from "$lib/paraglide/messages";
  import type { SaveFailure } from "./+page.server";

  /** `provisioning`: the organisation creates accounts at first sign-in (set on the overview). */
  type Props = { view: FederationView; provisioning: boolean };
  let { view, provisioning }: Props = $props();

  const eneo = getEneo();
  const copyState = createCopyState();

  const IDS: Record<FederationField, string> = {
    provider: "federation-provider",
    client_id: "federation-client-id",
    client_secret: "federation-client-secret",
    allowed_domains: "federation-domains"
  };
  const LABELS: Record<FederationField, () => string> = {
    provider: () => m.federation_admin_provider_label(),
    client_id: () => m.client_id(),
    client_secret: () => m.client_secret(),
    allowed_domains: () => m.federation_admin_domains()
  };

  // The settings the draft was made from. A save answers with the new ones;
  // a stale draft is refused with 409 instead of being merged.
  let base = $state.raw(untrack(() => view));
  let draft = $state(untrack(() => draftFromView(view)));
  let submitted = $state(false);
  let serverProblems = $state<Partial<Record<FederationField, FieldProblem>>>({});
  let confirming = $state(false);
  // What the open dialog lists, fixed when it opens: the save resets the draft.
  let confirmation = $state<{ lines: string[]; risky: boolean; effects: string[] }>({
    lines: [],
    risky: false,
    effects: []
  });
  // A Save with nothing changed says so instead of doing nothing silently.
  let nothingToSave = $state(false);
  // After a save that changed who can sign in: suggest trying it.
  let suggestTest = $state(false);
  let conflict = $state(false);
  let reloading = $state(false);
  let reloadFailed = $state(false);
  let formError = $state<string | null>(null);
  let copiedUri = $state<string | null>(null);
  let leaving = false;
  // Where focus goes when the dialog closes after a save.
  let focusAfterSave: (() => HTMLElement | null) | null = null;

  let saveButton = $state<HTMLButtonElement | null>(null);
  let replaceSecretButton = $state<HTMLButtonElement | null>(null);
  let conflictAlert = $state<HTMLElement | null>(null);
  let formErrorAlert = $state<HTMLElement | null>(null);

  const changed = $derived(changedFields(base, draft));
  const problems = $derived(validate(draft));
  // Account creation also needs domains to match (the sign-in refuses it with an empty list).
  const provisioningState = $derived(
    !provisioning
      ? m.federation_admin_jit_off()
      : parseDomains(draft.domains).length > 0
        ? m.federation_admin_jit_on()
        : m.federation_admin_jit_no_domains()
  );

  function problemFor(field: FederationField): FieldProblem | undefined {
    return (submitted ? problems[field] : undefined) ?? serverProblems[field];
  }

  function message(problem: FieldProblem): string {
    switch (problem.code) {
      case "required":
        return m.required_field();
      case "secret_required":
        return m.federation_admin_secret_required();
      case "secret_too_short":
        return m.federation_admin_secret_too_short({ min: problem.min });
      case "domain_invalid":
        return m.federation_admin_domain_invalid({ domain: problem.domain });
      case "secret_masked":
        return m.federation_admin_secret_masked();
      case "refused":
        return m.federation_admin_field_refused();
    }
  }

  /** The ids that describe a field: its help text, then its error when it has one. */
  function describedBy(field: FederationField, help?: string): string | undefined {
    const ids = [help, problemFor(field) ? `${IDS[field]}-error` : undefined].filter(Boolean);
    return ids.length ? ids.join(" ") : undefined;
  }

  function edited(field: FederationField) {
    nothingToSave = false;
    suggestTest = false;
    if (!serverProblems[field]) return;
    const { [field]: _, ...rest } = serverProblems;
    serverProblems = rest;
  }

  function focusField(field: FederationField) {
    document.getElementById(IDS[field])?.focus();
  }

  function startFrom(next: FederationView) {
    base = next;
    draft = draftFromView(next);
    submitted = false;
    serverProblems = {};
    formError = null;
  }

  async function requestSave(event: SubmitEvent) {
    event.preventDefault();
    // The button stays enabled, so focus can return to it after a save.
    if (confirming) return;
    if (changed.length === 0) {
      nothingToSave = true;
      return;
    }
    const first = FEDERATION_FIELDS.find((field) => problems[field]);
    if (first) {
      submitted = true;
      await tick();
      focusField(first);
      return;
    }
    formError = null;
    confirmation = {
      lines: changed.map(changeLine),
      risky: changed.some((field) => RISKY.has(field)),
      effects: consequences(base, draft).map(effectText)
    };
    confirming = true;
  }

  async function undo() {
    startFrom(base);
    nothingToSave = false;
    await tick();
    saveButton?.focus();
  }

  async function replaceSecret() {
    draft.secret = "";
    edited("client_secret");
    await tick();
    focusField("client_secret");
  }

  async function keepSecret() {
    draft.secret = null;
    edited("client_secret");
    await tick();
    replaceSecretButton?.focus();
  }

  async function copyUri(uri: string) {
    if (await copyState.copy(uri)) copiedUri = uri;
  }

  /** The confirmation's one save: the dialog stays open until the answer is handled. */
  async function save() {
    let result: ActionResult;
    try {
      const response = await fetch("?/save", {
        method: "POST",
        body: toFormData(base, draft),
        headers: { accept: "application/json", "x-sveltekit-action": "true" }
      });
      result = deserialize(await response.text());
    } catch {
      result = { type: "error", error: undefined };
    }

    if (result.type === "success") {
      startFrom((result.data as { view: FederationView }).view);
      toast.success(m.federation_admin_saved());
      suggestTest = confirmation.risky;
      focusAfterSave = () => saveButton;
      return;
    }
    if (result.type === "redirect") {
      // The session has ended: a full load to sign-in starts the app afresh.
      leaving = true;
      assignLocation(result.location);
      return;
    }
    // A typed secret is not kept around after a refused save.
    if (draft.secret !== null) draft.secret = "";
    const failure = result.type === "failure" ? (result.data?.failure as SaveFailure) : undefined;
    switch (failure?.code) {
      case "conflict":
        conflict = true;
        reloadFailed = false;
        focusAfterSave = () => conflictAlert;
        return;
      case "not_configured":
      case "disabled":
        void invalidate("admin:federation");
        return;
      case "fields": {
        serverProblems = Object.fromEntries(
          Object.entries(failure.fields).map(([field, code]) => [field, { code }])
        );
        const first = FEDERATION_FIELDS.find((field) => failure.fields[field]);
        if (first) focusAfterSave = () => document.getElementById(IDS[first]);
        return;
      }
      case "encryption_unavailable":
        formError = m.federation_admin_encryption_unavailable();
        break;
      case "endpoint_host":
        formError = m.federation_admin_endpoint_host_refused({ host: failure.host });
        break;
      default:
        formError = m.federation_admin_save_error();
    }
    focusAfterSave = () => formErrorAlert;
  }

  function afterDialog(event: Event) {
    const target = focusAfterSave;
    focusAfterSave = null;
    if (!target) return;
    event.preventDefault();
    void tick().then(() => target()?.focus());
  }

  async function reloadAfterConflict() {
    if (reloading) return;
    reloading = true;
    reloadFailed = false;
    try {
      const latest = await eneo.federation.get();
      if (!latest.configured) {
        void invalidate("admin:federation");
        return;
      }
      startFrom(latest);
      conflict = false;
      await tick();
      focusField("provider");
    } catch {
      reloadFailed = true;
    } finally {
      reloading = false;
    }
  }

  /** One line of the confirmation: the setting from what to what; never the secret. */
  function changeLine(field: FederationField): string {
    if (field === "client_secret") return m.federation_admin_secret_replaced_change();
    const list = (values: string[]) => values.join(", ");
    if (field === "allowed_domains") {
      // The domains added and removed, not two whole lists to compare.
      const { added, removed } = domainChange(base, draft);
      const changes = [
        added.length ? m.federation_admin_domains_added({ domains: list(added) }) : null,
        removed.length ? m.federation_admin_domains_removed({ domains: list(removed) }) : null
      ].filter((change) => change !== null);
      // Only the order changed: the whole lists say that.
      if (changes.length) {
        return m.federation_admin_change_domains({
          field: LABELS[field](),
          changes: changes.join("; ")
        });
      }
    }
    const [from, to] =
      field === "provider"
        ? [base.provider ?? "", draft.provider.trim()]
        : field === "client_id"
          ? [base.client_id ?? "", draft.clientId.trim()]
          : [list(base.allowed_domains ?? []), list(parseDomains(draft.domains))];
    return m.federation_admin_change({
      field: LABELS[field](),
      from: from || m.federation_admin_none(),
      to: to || m.federation_admin_none()
    });
  }

  function effectText(effect: Consequence): string {
    const list = (domains: string[]) => domains.join(", ");
    switch (effect.code) {
      case "client_id":
        return m.federation_admin_confirm_client_id();
      case "secret":
        return m.federation_admin_confirm_secret();
      case "domains_restricted":
        return m.federation_admin_confirm_domains_restricted({ domains: list(effect.domains) });
      case "domains_emptied":
        return m.federation_admin_confirm_domains_emptied();
      case "domains_removed":
        return m.federation_admin_confirm_domains_removed({ domains: list(effect.domains) });
      case "domains_added":
        return m.federation_admin_confirm_domains_added({ domains: list(effect.domains) });
    }
  }

  beforeNavigate((navigation) => {
    if (leaving || changed.length === 0) return;
    if (navigation.type === "leave" || !confirm(m.unsaved_changes_warning())) {
      navigation.cancel();
    }
  });
</script>

{#snippet fieldError(field: FederationField)}
  {@const problem = problemFor(field)}
  {#if problem}
    <Field.Error id="{IDS[field]}-error">{message(problem)}</Field.Error>
  {/if}
{/snippet}

<Settings.Group title={m.federation_admin_operator_owned()}>
  <div class="flex max-w-3xl flex-col gap-4">
    <p class="text-muted text-sm">{m.federation_admin_operator_owned_help()}</p>
    <dl class="grid gap-x-8 gap-y-4 sm:grid-cols-2">
      <div>
        <dt class="text-secondary text-sm">{m.federation_admin_discovery()}</dt>
        <dd class="mt-1 text-sm">
          <code class="font-medium wrap-anywhere">{base.discovery_endpoint ?? "—"}</code>
        </dd>
      </div>
      <div>
        <dt class="text-secondary text-sm">{m.federation_admin_issuer()}</dt>
        <dd class="mt-1 text-sm">
          <code class="font-medium wrap-anywhere">{base.issuer ?? "—"}</code>
        </dd>
      </div>
      <div class="sm:col-span-2">
        <dt class="text-secondary text-sm">{m.federation_admin_redirects()}</dt>
        <dd class="mt-1 text-sm">
          {#if base.redirect_uris_problem || !base.redirect_uris?.length}
            <span class="text-muted">{m.federation_admin_redirects_unavailable()}</span>
          {:else}
            <ul class="flex flex-col gap-2">
              {#each base.redirect_uris as uri (uri)}
                <li class="flex flex-wrap items-center gap-2">
                  <code class="min-w-0 font-medium wrap-anywhere">{uri}</code>
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label={m.federation_admin_copy_uri({ uri })}
                    onclick={() => copyUri(uri)}
                  >
                    <Copy aria-hidden="true" />
                    {copyState.copied && copiedUri === uri ? m.copied() : m.copy()}
                  </Button>
                </li>
              {/each}
            </ul>
            <!-- The button's name carries the URI, so its visible "Copied" is announced here. -->
            <span class="sr-only" role="status"
              >{copyState.copied && copiedUri
                ? m.federation_admin_uri_copied({ uri: copiedUri })
                : ""}</span
            >
          {/if}
        </dd>
      </div>
      <div>
        <dt class="text-secondary text-sm">{m.federation_admin_scopes()}</dt>
        <dd class="mt-1 text-sm font-medium">{(base.scopes ?? []).join(" ") || "—"}</dd>
      </div>
      <div>
        <dt class="text-secondary text-sm">{m.federation_admin_token_auth()}</dt>
        <dd class="mt-1 text-sm font-medium">{base.token_endpoint_auth_method ?? "—"}</dd>
      </div>
    </dl>
  </div>
</Settings.Group>

<Settings.Group title={m.federation_admin_editable()}>
  <form
    method="POST"
    action="?/save"
    class="flex max-w-2xl flex-col gap-5"
    novalidate
    onsubmit={requestSave}
  >
    {#if conflict}
      <Alert.Root bind:ref={conflictAlert} tabindex={-1}>
        <CircleAlert />
        <Alert.Title>{m.federation_admin_conflict_title()}</Alert.Title>
        <Alert.Description>
          <p>{m.federation_admin_conflict_description()}</p>
          {#if reloadFailed}
            <p class="text-destructive">{m.federation_admin_load_error()}</p>
          {/if}
          <Button
            size="sm"
            variant="outline"
            class="mt-2"
            aria-busy={reloading}
            onclick={reloadAfterConflict}
          >
            {m.federation_admin_conflict_reload()}
          </Button>
        </Alert.Description>
      </Alert.Root>
    {/if}

    <Field.Field>
      <Field.Label for={IDS.provider}>{m.federation_admin_provider_label()}</Field.Label>
      <Input
        id={IDS.provider}
        bind:value={draft.provider}
        oninput={() => edited("provider")}
        autocomplete="off"
        spellcheck={false}
        aria-invalid={problemFor("provider") ? true : undefined}
        aria-describedby={describedBy("provider", "federation-provider-help")}
      />
      <Field.Description id="federation-provider-help">
        {m.federation_admin_provider_help()}
      </Field.Description>
      {@render fieldError("provider")}
    </Field.Field>

    <Field.Field>
      <Field.Label for={IDS.client_id}>{m.client_id()}</Field.Label>
      <Input
        id={IDS.client_id}
        bind:value={draft.clientId}
        oninput={() => edited("client_id")}
        autocomplete="off"
        spellcheck={false}
        aria-invalid={problemFor("client_id") ? true : undefined}
        aria-describedby={describedBy("client_id", "federation-client-id-help")}
      />
      <Field.Description id="federation-client-id-help">
        {m.federation_admin_client_id_help()}
      </Field.Description>
      {@render fieldError("client_id")}
    </Field.Field>

    {#if draft.secret === null}
      <div role="group" aria-labelledby="federation-secret-label" class="flex flex-col gap-2">
        <p id="federation-secret-label" class="text-sm font-medium">{m.client_secret()}</p>
        <p id="federation-secret-saved" class="text-muted text-sm">
          {m.federation_admin_secret_saved({
            date: formatDateTime(base.client_secret_updated_at) || "—"
          })}
        </p>
        {#if base.encryption_status === "plaintext"}
          <Alert.Root>
            <CircleAlert />
            <Alert.Description>{m.federation_admin_secret_plaintext()}</Alert.Description>
          </Alert.Root>
        {/if}
        <Button
          bind:ref={replaceSecretButton}
          size="sm"
          variant="outline"
          class="w-fit"
          aria-describedby="federation-secret-saved"
          onclick={replaceSecret}
        >
          {m.federation_admin_secret_replace()}
        </Button>
      </div>
    {:else}
      <Field.Field>
        <Field.Label for={IDS.client_secret}>{m.client_secret()}</Field.Label>
        <Input
          id={IDS.client_secret}
          type="password"
          bind:value={draft.secret}
          oninput={() => edited("client_secret")}
          autocomplete="new-password"
          spellcheck={false}
          aria-invalid={problemFor("client_secret") ? true : undefined}
          aria-describedby={describedBy("client_secret", "federation-secret-help")}
        />
        <Field.Description id="federation-secret-help">
          {m.federation_admin_secret_help()}
        </Field.Description>
        {@render fieldError("client_secret")}
        <!-- Field stretches its direct children; the wrapper keeps the button its own width. -->
        <div>
          <Button size="sm" variant="outline" onclick={keepSecret}>
            {m.federation_admin_secret_keep()}
          </Button>
        </div>
      </Field.Field>
    {/if}

    <Field.Field>
      <Field.Label for={IDS.allowed_domains}>{m.federation_admin_domains()}</Field.Label>
      <Textarea
        id={IDS.allowed_domains}
        bind:value={draft.domains}
        oninput={() => edited("allowed_domains")}
        rows={4}
        spellcheck={false}
        aria-invalid={problemFor("allowed_domains") ? true : undefined}
        aria-describedby={describedBy(
          "allowed_domains",
          "federation-domains-help federation-provisioning-state"
        )}
      />
      <Field.Description id="federation-domains-help">
        {m.federation_admin_domains_help()}
      </Field.Description>
      <!-- The domains decide who may sign in; this setting decides whether newcomers get an account. -->
      <Field.Description id="federation-provisioning-state">
        <span>{provisioningState}</span>
        <a href={resolve("/admin")}
          >{m.federation_admin_jit_link({ setting: m.enable_provisioning() })}</a
        >
      </Field.Description>
      {@render fieldError("allowed_domains")}
    </Field.Field>

    {#if formError}
      <Alert.Root variant="destructive" bind:ref={formErrorAlert} tabindex={-1}>
        <CircleAlert />
        <Alert.Description>{formError}</Alert.Description>
      </Alert.Root>
    {/if}

    {#if suggestTest}
      <Alert.Root role="status">
        <CircleCheck />
        <Alert.Description>{m.federation_admin_saved_next_step()}</Alert.Description>
      </Alert.Root>
    {/if}

    <div class="flex flex-wrap items-center gap-3">
      <Button type="submit" class="w-fit" bind:ref={saveButton}>{m.save_changes()}</Button>
      {#if changed.length > 0}
        <Button variant="ghost" onclick={undo}>{m.federation_admin_undo()}</Button>
      {/if}
      <p class="text-muted text-sm" role="status">
        {#if changed.length > 0}
          {m.federation_admin_unsaved({
            fields: changed.map((field) => LABELS[field]()).join(", ")
          })}
        {:else if nothingToSave}
          {m.federation_admin_nothing_to_save()}
        {/if}
      </p>
    </div>
  </form>
</Settings.Group>

<ConfirmDialog
  bind:open={confirming}
  title={confirmation.risky
    ? m.federation_admin_confirm_title()
    : m.federation_admin_confirm_label_title()}
  description={confirmation.risky
    ? m.federation_admin_confirm_description()
    : m.federation_admin_confirm_label_description()}
  confirmLabel={m.federation_admin_confirm_action()}
  pendingLabel={m.saving()}
  variant={confirmation.risky ? "destructive" : "default"}
  width="medium"
  onConfirm={save}
  onCloseAutoFocus={afterDialog}
>
  <div class="flex flex-col gap-2 text-sm">
    <p class="font-medium">{m.federation_admin_confirm_changes()}</p>
    <ul class="list-disc space-y-1 pl-6">
      {#each confirmation.lines as line (line)}
        <li class="break-words">{line}</li>
      {/each}
    </ul>
    {#each confirmation.effects as effect (effect)}
      <p>{effect}</p>
    {/each}
    {#if confirmation.risky}
      <p class="text-muted">{m.federation_admin_confirm_recovery()}</p>
    {/if}
  </div>
</ConfirmDialog>
