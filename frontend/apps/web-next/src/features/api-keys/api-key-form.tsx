"use client";

import { createStaticSource, type SearchableItem } from "@astryxdesign/core/Typeahead";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { Tokenizer } from "@/components/astryx/tokenizer";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import {
  createRequest,
  draftProblems,
  effectivePermission,
  ipProblem,
  isLevelAllowed,
  listProblem,
  newApiKeyDraft,
  originProblem,
  RESOURCE_LEVELS,
  resourceLevel,
  visibleResources,
  withKeyType,
  withScopeType,
  type ApiKeyDraft,
  type DraftField,
  type ResourceKey
} from "./api-key-draft";
import {
  apiKeyPolicyConstraintsQueryOptions,
  invalidateApiKeys,
  withoutSecret,
  type ApiKeyCreationConstraints,
  type ApiKeyOwnership,
  type ApiKeyScopeType,
  type ApiKeyType,
  type ResourcePermissionLevel,
  type ResourceScopeType
} from "./api-keys";
import { ExpirationPicker, expiryInDays } from "./expiration-picker";
import { ScopeResourcePicker } from "./scope-resource-picker";

/** A key created from a resource's settings: its scope is that resource. */
export type LockedScope = { type: ResourceScopeType; id: string; name: string };

const SCOPE_TYPES: ApiKeyScopeType[] = ["tenant", "space", "assistant", "app"];
const ORIGIN_SUGGESTIONS = ["https://*", "http://localhost:*"];
const IP_SUGGESTIONS = ["10.0.0.0/8", "192.168.0.0/16"];
const FIELD_ORDER: DraftField[] = ["name", "scope", "origins", "ips", "expiry", "rateLimit"];

/** The default expiry: 30 days, unless the policy allows less (then the user picks). */
function defaultExpiry(constraints: ApiKeyCreationConstraints | undefined): string | null {
  const max = constraints?.max_expiration_days;
  return max != null && max < 30 ? null : expiryInDays(30);
}

/**
 * The fields of a create or edit key dialog, shared by the account page, the
 * admin page and the resource sections: name, description and key type;
 * ownership (admins), scope and per-resource access; the allowed origins of a
 * public key or the allowed IPs of a secret one, the expiry (on create) and
 * the rate limit. The tenant policy (`constraints`) bounds the expiry and the
 * rate limit. Problems show at their fields on submit and focus moves to the
 * first; an invalid origin or IP shows as soon as it is added. The checks are
 * a convenience: the backend enforces every one of them.
 */
export function ApiKeyForm({
  idPrefix,
  mode,
  initial,
  lockedScope,
  constraints,
  title,
  description,
  pending,
  error,
  onSubmit,
  onCancel
}: {
  /** Makes the field ids unique on the page. */
  idPrefix: string;
  mode: "create" | "edit";
  initial: ApiKeyDraft;
  /** Shown instead of the scope choice (a resource's own keys). */
  lockedScope?: LockedScope;
  constraints: ApiKeyCreationConstraints | undefined;
  title: string;
  description: string;
  pending: boolean;
  /** The last submit's failure; the input stays for a retry. */
  error: unknown;
  onSubmit: (draft: ApiKeyDraft) => void;
  onCancel: () => void;
}) {
  const t = useTranslations();
  const { can } = useAppContext();
  const [draft, setDraft] = useState(initial);
  const [submitted, setSubmitted] = useState(false);
  // What is typed into the origins or IPs field but not added as an entry yet.
  const [unadded, setUnadded] = useState("");
  const formRef = useRef<HTMLFormElement>(null);
  const id = (field: string) => `${idPrefix}-key-${field}`;
  const creating = mode === "create";
  const scopeType = draft.scopeType;
  const scopeLabel = t(`api_keys_scope_${scopeType}`);
  // Inside a sentence: "Välj assistent".
  const scopeNoun = scopeLabel.toLocaleLowerCase();

  const problems = draftProblems(draft, { mode, constraints }, t);
  // Typed but not added, a restriction would be dropped without a word: it
  // stops the submit until it is added or cleared.
  const allowlist = draft.keyType === "pk_" ? "origins" : "ips";
  if (unadded.trim()) {
    problems[allowlist] = t("api_keys_allowlist_unadded", { value: unadded.trim() });
  }
  // An invalid origin or IP is named as soon as it is added; the rest on submit.
  const live: Partial<Record<DraftField, string>> = {
    origins: invalidEntry(draft.allowedOrigins, originProblem, t),
    ips: invalidEntry(draft.allowedIps, ipProblem, t)
  };
  const shown = (field: DraftField) => (submitted ? problems[field] : live[field]) ?? null;
  const update = (patch: Partial<ApiKeyDraft>) => setDraft((current) => ({ ...current, ...patch }));

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const first = FIELD_ORDER.find((field) => problems[field]);
    if (first) {
      revealProblems(
        () => setSubmitted(true),
        formRef.current?.querySelector<HTMLElement>(
          `[data-field="${first}"] :is(input, button[role="radio"])`
        )
      );
      return;
    }
    onSubmit(draft);
  }

  return (
    <form ref={formRef} className="flex flex-col gap-6" noValidate onSubmit={submit}>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        <DialogDescription>{description}</DialogDescription>
      </DialogHeader>

      <Section title={t("api_keys_step_basic_info")}>
        <div className="flex flex-col gap-2" data-field="name">
          <Label htmlFor={id("name")}>{t("name")}</Label>
          <Input
            id={id("name")}
            value={draft.name}
            placeholder={t("api_keys_name_placeholder")}
            onChange={(event) => update({ name: event.target.value })}
            required
            {...fieldProblemProps(id("name"), shown("name"), `${id("name")}-help`)}
          />
          <p id={`${id("name")}-help`} className="text-muted-foreground text-xs">
            {t("api_keys_name_help")}
          </p>
          <FieldProblem id={id("name")} problem={shown("name")} />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor={id("description")}>{t("description")}</Label>
          <Textarea
            id={id("description")}
            value={draft.description}
            placeholder={t("api_keys_description_placeholder")}
            onChange={(event) => update({ description: event.target.value })}
          />
        </div>
        {creating ? (
          <ChoiceGroup
            id={id("type")}
            legend={t("api_keys_key_type")}
            value={draft.keyType}
            onChange={(keyType) => {
              setUnadded("");
              setDraft((current) => withKeyType(current, keyType as ApiKeyType));
            }}
            options={[
              {
                value: "sk_",
                label: t("api_keys_secret_key"),
                hint: t("api_keys_secret_key_desc")
              },
              { value: "pk_", label: t("api_keys_public_key"), hint: t("api_keys_public_key_desc") }
            ]}
          />
        ) : (
          <FixedValue
            label={t("api_keys_key_type")}
            value={draft.keyType === "pk_" ? t("api_keys_public_key") : t("api_keys_secret_key")}
          />
        )}
      </Section>

      <Section title={t("api_keys_step_scope")}>
        {can("admin") &&
          (creating ? (
            <ChoiceGroup
              id={id("ownership")}
              legend={t("api_keys_ownership_label")}
              value={draft.ownership}
              onChange={(ownership) => update({ ownership: ownership as ApiKeyOwnership })}
              options={[
                {
                  value: "user",
                  label: t("api_keys_ownership_user"),
                  hint: t("api_keys_ownership_user_desc")
                },
                {
                  value: "service",
                  label: t("api_keys_ownership_service"),
                  hint: t("api_keys_ownership_service_desc")
                }
              ]}
            />
          ) : (
            <FixedValue
              label={t("api_keys_ownership_label")}
              value={
                draft.ownership === "service"
                  ? t("api_keys_ownership_service")
                  : t("api_keys_ownership_user")
              }
            />
          ))}
        {draft.ownership === "service" && (
          <p className="text-muted-foreground text-xs">
            {t("api_keys_ownership_service_explainer")}
          </p>
        )}
        {draft.ownership === "service" &&
          scopeType === "tenant" &&
          effectivePermission(draft) !== "read" && (
            <p className="text-ax-warning text-xs">
              {t("api_keys_ownership_service_guardrail_hint")}
            </p>
          )}

        {!creating || lockedScope ? (
          <FixedValue
            label={t("api_keys_scope")}
            value={lockedScope ? `${scopeLabel} · ${lockedScope.name}` : scopeLabel}
            hint={creating ? t("api_keys_scope_locked") : t("api_keys_admin_edit_immutable_hint")}
          />
        ) : (
          <>
            <ChoiceGroup
              id={id("scope-type")}
              legend={t("api_keys_scope")}
              value={scopeType}
              onChange={(next) =>
                setDraft((current) => withScopeType(current, next as ApiKeyScopeType))
              }
              options={SCOPE_TYPES.map((option) => ({
                value: option,
                label: t(`api_keys_scope_${option}`),
                hint: t(`api_keys_scope_${option}_desc`)
              }))}
            />
            {scopeType !== "tenant" && (
              <div className="flex flex-col gap-3" data-field="scope">
                <ScopeResourcePicker
                  scopeType={scopeType}
                  value={draft.scopeId}
                  onChange={(scopeId) => update({ scopeId })}
                  label={t("api_keys_select_resource", { scopeType: scopeNoun })}
                  problem={shown("scope")}
                />
                <div className="flex flex-col gap-2">
                  <Label htmlFor={id("scope-id")}>
                    {t("api_keys_enter_id_manually", { scopeType: scopeNoun })}
                  </Label>
                  <Input
                    id={id("scope-id")}
                    className="font-mono"
                    value={draft.manualScopeId}
                    placeholder={t("api_keys_enter_uuid")}
                    onChange={(event) => update({ manualScopeId: event.target.value })}
                  />
                </div>
              </div>
            )}
          </>
        )}

        <ResourceAccess id={id("access")} draft={draft} onChange={update} />
      </Section>

      <Section title={t("api_keys_step_security")}>
        {draft.keyType === "pk_" ? (
          <AllowlistField
            key="origins"
            field="origins"
            label={t("api_keys_allowed_origins")}
            description={t("api_keys_allowed_origins_desc")}
            placeholder={t("apikey_origins_placeholder")}
            suggestions={ORIGIN_SUGGESTIONS}
            values={draft.allowedOrigins}
            onChange={(allowedOrigins) => update({ allowedOrigins })}
            onUnaddedChange={setUnadded}
            problem={shown("origins")}
            isRequired
          />
        ) : (
          <AllowlistField
            key="ips"
            field="ips"
            label={t("api_keys_allowed_ips")}
            description={t("api_keys_allowed_ips_desc")}
            placeholder={t("api_keys_allowed_ips_placeholder")}
            suggestions={IP_SUGGESTIONS}
            values={draft.allowedIps}
            onChange={(allowedIps) => update({ allowedIps })}
            onUnaddedChange={setUnadded}
            problem={shown("ips")}
          />
        )}
        {creating && (
          <div data-field="expiry">
            <ExpirationPicker
              id={id("expiry")}
              value={draft.expiresAt}
              onChange={(expiresAt) => update({ expiresAt })}
              maxDays={constraints?.max_expiration_days}
              required={constraints?.require_expiration ?? false}
              problem={shown("expiry")}
            />
          </div>
        )}
        <div className="flex flex-col gap-2" data-field="rateLimit">
          <Label htmlFor={id("rate-limit")}>{t("api_keys_rate_limit")}</Label>
          <Input
            id={id("rate-limit")}
            type="number"
            inputMode="numeric"
            min={1}
            max={constraints?.max_rate_limit ?? undefined}
            className="w-48"
            value={draft.rateLimit}
            placeholder={t("api_keys_rate_limit_placeholder")}
            onChange={(event) => update({ rateLimit: event.target.value })}
            {...fieldProblemProps(id("rate-limit"), shown("rateLimit"), `${id("rate-limit")}-help`)}
          />
          <p id={`${id("rate-limit")}-help`} className="text-muted-foreground text-xs">
            {t("api_keys_rate_limit_help")}
            {constraints?.max_rate_limit != null
              ? ` ${t("api_keys_rate_limit_max", { max: constraints.max_rate_limit })}`
              : null}
          </p>
          <FieldProblem id={id("rate-limit")} problem={shown("rateLimit")} />
        </div>
      </Section>

      {error != null && <ListError error={error} compact />}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          {t("cancel")}
        </Button>
        {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
        <Button type="submit" aria-busy={pending || undefined}>
          {!creating ? t("save") : pending ? t("api_keys_creating") : t("api_keys_create_short")}
        </Button>
      </DialogFooter>
    </form>
  );
}

function invalidEntry(
  values: string[],
  problemOf: (value: string) => string | null,
  t: (key: string) => string
): string | undefined {
  const invalid = listProblem(values, problemOf);
  return invalid ? `${invalid.value}: ${t(invalid.key)}` : undefined;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

/** A setting that cannot change here, shown as text. */
function FixedValue({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-sm font-medium">{label}</span>
      <span className="text-sm">{value}</span>
      {hint && <span className="text-muted-foreground text-xs">{hint}</span>}
    </div>
  );
}

function ChoiceGroup({
  id,
  legend,
  value,
  onChange,
  options
}: {
  id: string;
  legend: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; hint: string }[];
}) {
  const legendId = `${id}-legend`;
  return (
    <fieldset className="flex flex-col gap-2">
      <legend id={legendId} className="mb-2 text-sm font-medium">
        {legend}
      </legend>
      <RadioGroup
        value={value}
        onValueChange={onChange}
        aria-labelledby={legendId}
        className="grid gap-3 sm:grid-cols-2"
      >
        {options.map((option) => {
          const itemId = `${id}-${option.value}`;
          return (
            <div key={option.value} className="flex items-start gap-2 rounded-lg border p-3">
              <RadioGroupItem
                id={itemId}
                value={option.value}
                className="mt-0.5"
                aria-describedby={`${itemId}-hint`}
              />
              <div className="flex flex-col gap-0.5">
                <Label htmlFor={itemId}>{option.label}</Label>
                <span id={`${itemId}-hint`} className="text-muted-foreground text-xs">
                  {option.hint}
                </span>
              </div>
            </div>
          );
        })}
      </RadioGroup>
    </fieldset>
  );
}

const RESOURCE_LABEL: Record<ResourceKey, string> = {
  assistants: "api_keys_resource_assistants",
  apps: "api_keys_resource_applications",
  spaces: "api_keys_resource_spaces",
  knowledge: "api_keys_resource_knowledge",
  conversations: "api_keys_resource_conversations",
  files: "api_keys_resource_files",
  jobs: "api_keys_resource_jobs",
  prompts: "api_keys_resource_prompts"
};

export const RESOURCE_LEVEL_LABEL: Record<ResourcePermissionLevel, string> = {
  none: "api_keys_permission_no_access",
  read: "api_keys_permission_read",
  write: "api_keys_permission_write",
  admin: "api_keys_permission_admin"
};

/** A resource type's name; the key's own assistant or app when it is scoped to one. */
export function resourceLabelKey(key: ResourceKey, scopeType: ApiKeyScopeType): string {
  if (key === "assistants" && scopeType === "assistant") {
    return "api_keys_resource_selected_assistant";
  }
  if (key === "apps" && scopeType === "app") return "api_keys_resource_selected_app";
  return RESOURCE_LABEL[key];
}

/** Per resource type: no access, read, write or admin, within what the scope and key type allow. */
function ResourceAccess({
  id,
  draft,
  onChange
}: {
  id: string;
  draft: ApiKeyDraft;
  onChange: (patch: Partial<ApiKeyDraft>) => void;
}) {
  const t = useTranslations();
  const resources = visibleResources(draft);
  const enabled = resources.filter((key) => resourceLevel(draft, key) !== "none").length;
  const publicKey = draft.keyType === "pk_";

  return (
    <fieldset className="flex flex-col gap-3" aria-describedby={`${id}-hint`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-0.5">
          <legend className="text-sm font-medium">
            {publicKey ? t("api_keys_public_resource_access") : t("api_keys_resource_access")}
          </legend>
          <span id={`${id}-hint`} className="text-muted-foreground text-xs">
            {publicKey
              ? t("api_keys_public_resource_access_desc")
              : t("api_keys_resource_access_desc")}
          </span>
        </div>
        <span className="text-muted-foreground shrink-0 text-xs">
          {t("api_keys_of_enabled", { count: enabled, total: resources.length })}
        </span>
      </div>
      <ul className="divide-y rounded-lg border">
        {resources.map((key) => {
          const triggerId = `${id}-${key}`;
          const labelKey = resourceLabelKey(key, draft.scopeType);
          return (
            <li key={key} className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-center">
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <Label htmlFor={triggerId}>{t(labelKey)}</Label>
                <span id={`${triggerId}-hint`} className="text-muted-foreground text-xs">
                  {t(`${labelKey}_desc`)}
                </span>
              </div>
              <Select
                value={resourceLevel(draft, key)}
                onValueChange={(level) =>
                  onChange({
                    resourcePermissions: {
                      ...draft.resourcePermissions,
                      [key]: level as ResourcePermissionLevel
                    }
                  })
                }
              >
                <SelectTrigger
                  id={triggerId}
                  className="w-full sm:w-36"
                  aria-describedby={`${triggerId}-hint`}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RESOURCE_LEVELS.map((level) => (
                    <SelectItem
                      key={level}
                      value={level}
                      disabled={!isLevelAllowed(draft, key, level)}
                    >
                      {t(RESOURCE_LEVEL_LABEL[level])}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}

/**
 * The origins (public keys) or IPs (secret keys) a key is restricted to, as
 * removable tokens: typed and added with Enter, or picked from the common
 * patterns offered on focus.
 */
function AllowlistField({
  field,
  label,
  description,
  placeholder,
  suggestions,
  values,
  onChange,
  onUnaddedChange,
  problem,
  isRequired = false
}: {
  field: DraftField;
  label: string;
  description: string;
  placeholder: string;
  suggestions: string[];
  values: string[];
  onChange: (values: string[]) => void;
  /** The text typed but not added as an entry (Astryx clears it on add without saying so). */
  onUnaddedChange: (text: string) => void;
  problem: string | null;
  isRequired?: boolean;
}) {
  const t = useTranslations();
  const source = useMemo(
    () =>
      createStaticSource<SearchableItem>(suggestions.map((value) => ({ id: value, label: value }))),
    [suggestions]
  );
  // Stable between keystrokes: the field re-renders as the typed text is reported.
  const tokens = useMemo(() => values.map((value) => ({ id: value, label: value })), [values]);
  return (
    <div data-field={field}>
      <Tokenizer
        label={label}
        description={description}
        placeholder={placeholder}
        searchSource={source}
        value={tokens}
        onChange={(items, change) => {
          // Adding takes the typed text; removing a token leaves it in the field.
          if (change.type === "add" || change.type === "create") onUnaddedChange("");
          onChange(items.map((item) => item.id.trim()).filter(Boolean));
        }}
        onChangeQuery={onUnaddedChange}
        hasCreate
        hasEntriesOnFocus
        debounceMs={0}
        isRequired={isRequired}
        isOptional={!isRequired}
        emptySearchResultsText={t("no_results")}
        status={problem ? { type: "error", message: problem } : undefined}
        width="100%"
      />
    </div>
  );
}

/**
 * The "Create" button and dialog for a new key, on the account page, the
 * admin page or a resource's settings (`lockedScope`). The policy is read when
 * it opens. The secret goes to `onCreated` for the one-time reveal and is kept
 * nowhere else; a failed create keeps the dialog and its input.
 */
export function CreateApiKeyDialog({
  trigger,
  idPrefix,
  lockedScope,
  defaultOwnership = "user",
  onCreated
}: {
  trigger: ReactNode;
  idPrefix: string;
  lockedScope?: LockedScope;
  defaultOwnership?: ApiKeyOwnership;
  onCreated: (secret: string) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const constraints = useQuery({
    ...apiKeyPolicyConstraintsQueryOptions(browserApi),
    enabled: open
  });
  const secret = useRef<string | null>(null);
  const title = lockedScope
    ? t("api_keys_create_for_resource", { resource: lockedScope.name })
    : t("api_keys_create");

  const create = useMutation({
    mutationFn: (draft: ApiKeyDraft) =>
      withoutSecret(
        unwrap(browserApi.POST("/api/v1/api-keys", { body: createRequest(draft) })),
        (value) => {
          secret.current = value;
        }
      ),
    onSuccess: () => {
      invalidateApiKeys(queryClient);
      setOpen(false);
      if (secret.current) onCreated(secret.current);
      secret.current = null;
    }
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) create.reset();
      }}
    >
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        {constraints.isPending ? (
          <>
            <DialogHeader>
              <DialogTitle>{title}</DialogTitle>
            </DialogHeader>
            <LoadingState rows={4} />
          </>
        ) : (
          <ApiKeyForm
            idPrefix={idPrefix}
            mode="create"
            initial={{
              ...newApiKeyDraft({
                scopeType: lockedScope?.type,
                scopeId: lockedScope?.id,
                ownership: defaultOwnership
              }),
              expiresAt: defaultExpiry(constraints.data)
            }}
            lockedScope={lockedScope}
            // Without the policy (it failed to load) the backend still enforces it.
            constraints={constraints.data}
            title={title}
            description={t("generate_api_key_warning")}
            pending={create.isPending}
            error={create.error}
            onSubmit={(draft) => create.mutate(draft)}
            onCancel={() => setOpen(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
