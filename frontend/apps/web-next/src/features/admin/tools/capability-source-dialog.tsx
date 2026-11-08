import { invalidateSpaces } from "@/features/spaces/space";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useRef, useState, type SubmitEvent } from "react";
import {
  ConfirmedSecretInput,
  confirmedSecretProblem
} from "@/components/composites/confirmed-secret-input";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { modelProvidersQueryOptions } from "@/features/admin/governance/governance";
import { AddModelWizard } from "@/features/admin/models/add-model-wizard";
import { useImageOptionLabels } from "@/features/admin/models/image-model-options";
import { modelsHref } from "@/features/admin/models/provider-sections";
import { userGroupsQueryOptions } from "@/features/admin/user-groups/user-groups";
import { readinessKey, type Capability } from "@/features/capabilities/capabilities";
import { CATALOG_LIMITS } from "../mcp/mcp-settings";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { createMcpServer, MCP_KEY, updateMcpServer, type McpServer } from "../mcp/mcp";
import {
  createSourcePayload,
  sourceDraft,
  sourceDraftProblems,
  updateSourcePayload,
  type SourceField,
  type SourceProblem
} from "./capability-source";

/** The fields that can hold a problem, in the order the form shows them. */
const FIELD_ORDER = [
  "imageModel",
  "url",
  "headerName",
  "token",
  "tokenConfirmation",
  "name",
  "groups",
  "priority",
  "toolCatalogMaxCount",
  "toolCatalogMaxMiB",
  "toolDefinitionMaxKiB"
] as const;
type FormField = (typeof FIELD_ORDER)[number];

/** The element each field focuses (the token fields have refs instead). */
const FIELD_IDS = {
  imageModel: "source-model",
  url: "source-url",
  headerName: "source-header",
  name: "source-name",
  groups: "source-groups",
  priority: "source-priority",
  toolCatalogMaxCount: "source-max-tools",
  toolCatalogMaxMiB: "source-max-catalog",
  toolDefinitionMaxKiB: "source-max-definition"
} satisfies Partial<Record<FormField, string>>;

export function CapabilitySourceDialog({
  purpose,
  server,
  replacesDefault,
  onClose,
  onSaved
}: {
  purpose: Capability;
  server?: McpServer | null;
  replacesDefault?: string;
  onClose: () => void;
  onSaved: (createdInactive: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => sourceDraft(server));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [tokenConfirmation, setTokenConfirmation] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [modelWizardOpen, setModelWizardOpen] = useState(false);
  const imageLabels = useImageOptionLabels();
  const tokenRef = useRef<HTMLInputElement>(null);
  const tokenConfirmationRef = useRef<HTMLInputElement>(null);
  const { data: security } = useQuery(securityClassificationsQueryOptions(browserApi));
  const groups = useQuery({ ...userGroupsQueryOptions(browserApi), retry: false });
  const models = useQuery({
    queryKey: ["image-models"],
    queryFn: async () => (await unwrap(browserApi.GET("/api/v1/image-models/"))).items,
    enabled: purpose === "image_generation" && draft.source === "builtin",
    retry: false
  });
  const providers = useQuery({
    ...modelProvidersQueryOptions(browserApi),
    enabled: purpose === "image_generation" && draft.source === "builtin",
    retry: false
  });
  const imageModels = (models.data ?? []).filter(
    (model) =>
      model.is_org_enabled &&
      !model.is_deprecated &&
      model.provider_id &&
      providers.data?.some((provider) => provider.id === model.provider_id && provider.is_active)
  );
  const persistedModel =
    server?.image_model_id && !imageModels.some((model) => model.id === server.image_model_id)
      ? (models.data?.find((model) => model.id === server.image_model_id) ?? server.image_model)
      : null;
  const selectedModel = models.data?.find((model) => model.id === draft.imageModelId);
  const inheritedClassification = selectedModel
    ? selectedModel.security_classification
    : draft.imageModelId === server?.image_model_id
      ? server.security_classification
      : null;
  const problems = sourceDraftProblems(draft, server);
  const tokenMismatch =
    draft.source === "external" &&
    draft.auth !== "none" &&
    confirmedSecretProblem({ value: draft.token, confirmation: tokenConfirmation }) === "mismatch";
  const problemText = (problem: SourceProblem) =>
    problem.kind === "required"
      ? t("required_field")
      : problem.kind === "no-group"
        ? t("form_problem_choose_group")
        : problem.kind === "credential-transport"
          ? t("mcp_credential_requires_https")
          : problem.max === undefined
            ? t("form_problem_whole_number_from", { min: problem.min })
            : t("form_problem_whole_number_between", { min: problem.min, max: problem.max });
  /** The field's problem, once the form was submitted. */
  const problemAt = (field: SourceField) => {
    const problem = submitted ? problems.find((candidate) => candidate.field === field) : null;
    return problem ? problemText(problem) : null;
  };
  const set = <Key extends keyof typeof draft>(key: Key, value: (typeof draft)[Key]) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const changed = JSON.stringify(draft) !== JSON.stringify(sourceDraft(server));

  function close() {
    if (busy) return;
    if (changed && !saved && !window.confirm(t("unsaved_changes_warning"))) return;
    onClose();
  }

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const withProblems = new Set<FormField>(problems.map((problem) => problem.field));
    if (tokenMismatch) withProblems.add("tokenConfirmation");
    const firstProblem = FIELD_ORDER.find((field) => withProblems.has(field));
    if (firstProblem) {
      // Advanced fields sit in a closed details, which revealProblems opens.
      revealProblems(
        () => setSubmitted(true),
        firstProblem === "token"
          ? tokenRef.current
          : firstProblem === "tokenConfirmation"
            ? tokenConfirmationRef.current
            : FIELD_IDS[firstProblem]
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (server) await updateMcpServer(browserApi, server.id, updateSourcePayload(server, draft));
      else await createMcpServer(browserApi, createSourcePayload(purpose, draft));
      setSaved(true);
      onSaved(!server && draft.source === "external");
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: MCP_KEY }),
        invalidateSpaces(queryClient)
      ]).catch((cause) => toastApiError(cause, t));
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open) close();
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {server ? t("tools_change") : t("tools_add_source")} · {t(purpose)}
            </DialogTitle>
            <DialogDescription>{t("tools_functions_description")}</DialogDescription>
          </DialogHeader>
          {/* Problems show at their fields on submit, and focus moves to the first. */}
          <form className="space-y-5" noValidate onSubmit={(event) => void submit(event)}>
            {error != null && <ListError error={error} title={t("save_failed")} />}
            {purpose === "image_generation" && (
              <div className="space-y-2">
                <Label htmlFor="source-type">{t("mcp_source_label")}</Label>
                <select
                  id="source-type"
                  className="border-input h-9 w-full rounded-md border bg-transparent px-2 text-base pointer-coarse:min-h-11 md:pointer-fine:text-sm"
                  value={draft.source}
                  disabled={server?.is_enabled}
                  onChange={(event) =>
                    set("source", event.target.value === "builtin" ? "builtin" : "external")
                  }
                >
                  <option value="external">{t("tools_source_external")}</option>
                  <option value="builtin">{t("tools_source_model")}</option>
                </select>
              </div>
            )}
            {draft.source === "builtin" ? (
              <div className="space-y-2">
                <Label htmlFor="source-model">{t("tools_source_model")}</Label>
                <select
                  id="source-model"
                  className="border-input h-9 w-full rounded-md border bg-transparent px-2 text-base pointer-coarse:min-h-11 md:pointer-fine:text-sm"
                  value={draft.imageModelId}
                  onChange={(event) => set("imageModelId", event.target.value)}
                  {...fieldProblemProps("source-model", problemAt("imageModel"))}
                >
                  <option value="">{t("select")}</option>
                  {persistedModel && (
                    <option value={persistedModel.id}>
                      {persistedModel.nickname || persistedModel.name}
                    </option>
                  )}
                  {imageModels.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.nickname || model.name}
                      {model.provider_name ? ` · ${model.provider_name}` : ""}
                    </option>
                  ))}
                </select>
                <FieldProblem id="source-model" problem={problemAt("imageModel")} />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => setModelWizardOpen(true)}
                >
                  {t("tools_add_image_model")}
                </Button>
                {server?.readiness_reason && draft.imageModelId === server.image_model_id && (
                  <p className="text-warning text-sm">{t(readinessKey(server.readiness_reason))}</p>
                )}
                {selectedModel && (
                  <p className="text-muted-foreground text-sm">
                    {selectedModel.name} · {t("image_default_size")}:{" "}
                    {imageLabels.size(selectedModel.default_size)} · {t("image_default_quality")}:{" "}
                    {imageLabels.quality(selectedModel.default_quality)}
                  </p>
                )}
                {security?.security_enabled && (
                  <div className="space-y-1">
                    <p className="text-sm">
                      {inheritedClassification?.name ?? t("no_classification")}
                    </p>
                    <p className="text-muted-foreground text-sm">
                      {t("mcp_builtin_classification_inherited")}
                    </p>
                  </div>
                )}
                <QueryStateBoundary queries={[models, providers]} rows={1}>
                  {() =>
                    imageModels.length === 0 ? (
                      <p className="text-muted-foreground text-sm">
                        {t("mcp_builtin_no_image_models")}{" "}
                        <Link className="underline" href={modelsHref("image")}>
                          {t("models")}
                        </Link>
                      </p>
                    ) : null
                  }
                </QueryStateBoundary>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="source-url">{t("url")}</Label>
                  <Input
                    id="source-url"
                    type="url"
                    value={draft.url}
                    required
                    onChange={(event) => set("url", event.target.value)}
                    {...fieldProblemProps("source-url", problemAt("url"))}
                  />
                  <FieldProblem id="source-url" problem={problemAt("url")} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="source-auth">{t("mcp_authentication")}</Label>
                  <select
                    id="source-auth"
                    className="border-input h-9 w-full rounded-md border bg-transparent px-2 text-base pointer-coarse:min-h-11 md:pointer-fine:text-sm"
                    value={draft.auth}
                    onChange={(event) =>
                      set(
                        "auth",
                        event.target.value === "bearer"
                          ? "bearer"
                          : event.target.value === "api_key_header"
                            ? "api_key_header"
                            : "none"
                      )
                    }
                  >
                    <option value="none">{t("mcp_auth_none")}</option>
                    <option value="bearer">{t("mcp_auth_bearer")}</option>
                    <option value="api_key_header">{t("api_key_header_auth")}</option>
                  </select>
                </div>
                {draft.auth === "api_key_header" && (
                  <div className="space-y-2">
                    <Label htmlFor="source-header">{t("api_key_header_name")}</Label>
                    <Input
                      id="source-header"
                      value={draft.headerName}
                      onChange={(event) => set("headerName", event.target.value)}
                      {...fieldProblemProps("source-header", problemAt("headerName"))}
                    />
                    <FieldProblem id="source-header" problem={problemAt("headerName")} />
                    {server?.http_auth_type === "api_key_header" && (
                      <p className="text-muted-foreground text-sm">
                        {t("api_key_header_name_keep_hint")}
                      </p>
                    )}
                  </div>
                )}
                {draft.auth !== "none" && (
                  <ConfirmedSecretInput
                    label={t(draft.auth === "bearer" ? "bearer_token" : "mcp_api_key_token")}
                    confirmLabel={t(
                      draft.auth === "bearer" ? "confirm_bearer_token" : "confirm_api_key"
                    )}
                    value={draft.token}
                    confirmation={tokenConfirmation}
                    onValueChange={(value) => set("token", value)}
                    onConfirmationChange={setTokenConfirmation}
                    // A saved credential may be left as it is.
                    isRequired={server?.http_auth_type !== draft.auth}
                    requiredMessage={t("required_field")}
                    valueError={problemAt("token") ?? undefined}
                    mismatchMessage={t("secret_values_do_not_match")}
                    showErrors={submitted}
                    autoComplete="off"
                    placeholder={server?.credential_preview ?? undefined}
                    valueRef={tokenRef}
                    confirmationRef={tokenConfirmationRef}
                  />
                )}
                {security?.security_enabled && (
                  <div className="space-y-2">
                    <Label htmlFor="source-classification">{t("security_classification")}</Label>
                    <select
                      id="source-classification"
                      className="border-input h-9 w-full rounded-md border bg-transparent px-2 text-base pointer-coarse:min-h-11 md:pointer-fine:text-sm"
                      value={draft.classificationId}
                      onChange={(event) => set("classificationId", event.target.value)}
                    >
                      <option value="">{t("none")}</option>
                      {security.security_classifications.map((classification) => (
                        <option key={classification.id} value={classification.id}>
                          {classification.name}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                <div className="flex items-center justify-between gap-3">
                  <Label htmlFor="source-forward-identity">{t("mcp_forward_identity")}</Label>
                  <Switch
                    id="source-forward-identity"
                    checked={draft.forwardIdentity}
                    onCheckedChange={(value) => set("forwardIdentity", value)}
                    aria-describedby="source-forward-identity-hint"
                  />
                </div>
                <p id="source-forward-identity-hint" className="text-muted-foreground text-sm">
                  {t(`${purpose}_forward_identity_hint`)}
                </p>
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="source-name">{t("name")}</Label>
              <Input
                id="source-name"
                value={draft.name}
                required
                onChange={(event) => set("name", event.target.value)}
                {...fieldProblemProps("source-name", problemAt("name"))}
              />
              <FieldProblem id="source-name" problem={problemAt("name")} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="source-description">{t("description")}</Label>
              <Textarea
                id="source-description"
                rows={2}
                value={draft.description}
                onChange={(event) => set("description", event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="source-audience">{t("mcp_audience_label")}</Label>
              <select
                id="source-audience"
                className="border-input h-9 w-full rounded-md border bg-transparent px-2 text-base pointer-coarse:min-h-11 md:pointer-fine:text-sm"
                value={draft.audience}
                onChange={(event) =>
                  set("audience", event.target.value === "groups" ? "groups" : "everyone")
                }
              >
                <option value="everyone">{t("mcp_audience_everyone")}</option>
                <option value="groups">{t("mcp_audience_groups")}</option>
              </select>
            </div>
            {draft.audience === "groups" && (
              <fieldset
                id="source-groups"
                className="space-y-2 rounded-lg border p-3"
                {...fieldProblemProps("source-groups", problemAt("groups"))}
              >
                <legend className="px-1 text-sm font-medium">{t("mcp_audience_groups")}</legend>
                <QueryStateBoundary query={groups} rows={2}>
                  {(items) =>
                    items.length ? (
                      items.map((group) => (
                        <label key={group.id} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={draft.groupIds.includes(group.id)}
                            onChange={(event) =>
                              set(
                                "groupIds",
                                event.target.checked
                                  ? [...draft.groupIds, group.id]
                                  : draft.groupIds.filter((id) => id !== group.id)
                              )
                            }
                          />
                          {group.name}
                        </label>
                      ))
                    ) : (
                      <p className="text-muted-foreground text-sm">{t("mcp_audience_no_groups")}</p>
                    )
                  }
                </QueryStateBoundary>
                <FieldProblem id="source-groups" problem={problemAt("groups")} />
              </fieldset>
            )}
            <div className="space-y-2">
              <Label htmlFor="source-priority">{t("mcp_audience_priority")}</Label>
              <Input
                id="source-priority"
                type="number"
                min={0}
                step={1}
                value={draft.priority}
                onChange={(event) => set("priority", Number(event.target.value))}
                {...fieldProblemProps("source-priority", problemAt("priority"))}
              />
              <FieldProblem id="source-priority" problem={problemAt("priority")} />
            </div>
            <details className="rounded-lg border p-3">
              <summary className="cursor-pointer text-sm font-medium">
                {t("skills_advanced_options")}
              </summary>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="source-docs">{t("mcp_documentation_url")}</Label>
                  <Input
                    id="source-docs"
                    type="url"
                    value={draft.documentationUrl}
                    onChange={(event) => set("documentationUrl", event.target.value)}
                  />
                </div>
                {CATALOG_LIMITS.map(({ field, label, max }) => (
                  <div key={field} className="space-y-2">
                    <Label htmlFor={FIELD_IDS[field]}>{t(label)}</Label>
                    <Input
                      id={FIELD_IDS[field]}
                      type="number"
                      min={1}
                      max={max}
                      step={1}
                      value={draft[field]}
                      onChange={(event) => set(field, Number(event.target.value))}
                      {...fieldProblemProps(FIELD_IDS[field], problemAt(field))}
                    />
                    <FieldProblem id={FIELD_IDS[field]} problem={problemAt(field)} />
                  </div>
                ))}
              </div>
            </details>
            {server?.is_enabled && (
              <p className="text-muted-foreground text-sm">{t("tools_source_replacement_hint")}</p>
            )}
            {!server &&
              draft.source === "builtin" &&
              draft.audience === "everyone" &&
              replacesDefault && (
                <p className="text-muted-foreground text-sm">
                  {t("tools_replace_default", { name: replacesDefault })}
                </p>
              )}
            <div className="flex justify-end gap-2 border-t pt-4">
              <Button type="button" variant="outline" disabled={busy} onClick={close}>
                {t("cancel")}
              </Button>
              {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
              <Button type="submit" aria-busy={busy || undefined}>
                {busy
                  ? t("saving")
                  : !server && draft.source === "builtin"
                    ? t("tools_save_activate")
                    : t("save")}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <AddModelWizard
        open={modelWizardOpen}
        onOpenChange={setModelWizardOpen}
        fixedKind="image"
        onCreated={(ids) => {
          const first = ids[0];
          if (first) set("imageModelId", first);
          void queryClient.invalidateQueries({ queryKey: ["image-models"] });
        }}
      />
    </>
  );
}
