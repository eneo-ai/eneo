"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState, type SubmitEvent } from "react";
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
import type { Capability } from "@/features/capabilities/capabilities";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { createMcpServer, MCP_KEY, updateMcpServer, type McpServer } from "../mcp/mcp";
import {
  createSourcePayload,
  sourceDraft,
  sourceDraftValid,
  updateSourcePayload
} from "./capability-source";

export function CapabilitySourceDialog({
  purpose,
  server,
  onClose,
  onSaved
}: {
  purpose: Capability;
  server?: McpServer | null;
  onClose: () => void;
  onSaved: (createdInactive: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(() => sourceDraft(server));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [tokenConfirmation, setTokenConfirmation] = useState("");
  const { data: security } = useQuery(securityClassificationsQueryOptions(browserApi));
  const groups = useQuery({
    queryKey: ["user-groups"],
    queryFn: async () => (await unwrap(browserApi.GET("/api/v1/user-groups/"))).items,
    retry: false
  });
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
      ? models.data?.find((model) => model.id === server.image_model_id)
      : null;
  const tokenMatches = !draft.token || draft.token === tokenConfirmation;
  const valid = sourceDraftValid(draft, server) && tokenMatches;
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
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (server) await updateMcpServer(browserApi, server.id, updateSourcePayload(server, draft));
      else await createMcpServer(browserApi, createSourcePayload(purpose, draft));
      setSaved(true);
      onSaved(!server && draft.source === "external");
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: MCP_KEY }),
        queryClient.invalidateQueries({ queryKey: ["spaces"] })
      ]).catch((cause) => toastApiError(cause, t));
    } catch (cause) {
      setError(getErrorMessage(cause, t));
    } finally {
      setBusy(false);
    }
  }

  return (
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
        <form className="space-y-5" onSubmit={(event) => void submit(event)}>
          {error && (
            <p className="text-destructive text-sm" role="alert">
              {error}
            </p>
          )}
          {purpose === "image_generation" && (
            <div className="space-y-2">
              <Label htmlFor="source-type">{t("mcp_source_label")}</Label>
              <select
                id="source-type"
                className="border-input bg-background h-9 w-full rounded-md border px-2"
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
                className="border-input bg-background h-9 w-full rounded-md border px-2"
                value={draft.imageModelId}
                onChange={(event) => set("imageModelId", event.target.value)}
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
              {(models.isPending || providers.isPending) && (
                <p className="text-muted-foreground text-sm">{t("loading")}</p>
              )}
              {(models.isError || providers.isError) && (
                <p className="text-destructive text-sm" role="alert">
                  {t("request_failed")}
                </p>
              )}
              {!models.isPending && !providers.isPending && imageModels.length === 0 && (
                <p className="text-muted-foreground text-sm">
                  {t("mcp_builtin_no_image_models")}{" "}
                  <Link className="underline" href="/admin/models">
                    {t("models")}
                  </Link>
                </p>
              )}
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
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="source-auth">{t("mcp_authentication")}</Label>
                <select
                  id="source-auth"
                  className="border-input bg-background h-9 w-full rounded-md border px-2"
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
                  />
                </div>
              )}
              {draft.auth !== "none" && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="source-token">
                      {t(draft.auth === "bearer" ? "bearer_token" : "mcp_api_key_token")}
                    </Label>
                    <Input
                      id="source-token"
                      type="password"
                      autoComplete="off"
                      value={draft.token}
                      placeholder={server?.credential_preview ?? undefined}
                      onChange={(event) => set("token", event.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="source-token-confirm">{t("confirm_bearer_token")}</Label>
                    <Input
                      id="source-token-confirm"
                      type="password"
                      autoComplete="off"
                      value={tokenConfirmation}
                      onChange={(event) => setTokenConfirmation(event.target.value)}
                    />
                  </div>
                  {!tokenMatches && (
                    <p role="alert" className="text-destructive text-sm">
                      {t("secret_values_do_not_match")}
                    </p>
                  )}
                </div>
              )}
              {security?.security_enabled && (
                <div className="space-y-2">
                  <Label htmlFor="source-classification">{t("security_classification")}</Label>
                  <select
                    id="source-classification"
                    className="border-input bg-background h-9 w-full rounded-md border px-2"
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
                />
              </div>
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="source-name">{t("name")}</Label>
            <Input
              id="source-name"
              value={draft.name}
              required
              onChange={(event) => set("name", event.target.value)}
            />
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
              className="border-input bg-background h-9 w-full rounded-md border px-2"
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
            <fieldset className="space-y-2 rounded-lg border p-3">
              <legend className="px-1 text-sm font-medium">{t("mcp_audience_groups")}</legend>
              {groups.isPending ? (
                <p>{t("loading")}</p>
              ) : groups.isError ? (
                <p role="alert">{t("request_failed")}</p>
              ) : groups.data?.length ? (
                groups.data.map((group) => (
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
              )}
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
            />
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
              <div className="space-y-2">
                <Label htmlFor="source-max-tools">{t("mcp_catalog_max_count")}</Label>
                <Input
                  id="source-max-tools"
                  type="number"
                  min={1}
                  max={4096}
                  value={draft.toolCatalogMaxCount}
                  onChange={(event) => set("toolCatalogMaxCount", Number(event.target.value))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="source-max-catalog">{t("mcp_catalog_max_mib")}</Label>
                <Input
                  id="source-max-catalog"
                  type="number"
                  min={1}
                  max={64}
                  value={draft.toolCatalogMaxMiB}
                  onChange={(event) => set("toolCatalogMaxMiB", Number(event.target.value))}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="source-max-definition">{t("mcp_tool_definition_max_kib")}</Label>
                <Input
                  id="source-max-definition"
                  type="number"
                  min={1}
                  max={1024}
                  value={draft.toolDefinitionMaxKiB}
                  onChange={(event) => set("toolDefinitionMaxKiB", Number(event.target.value))}
                />
              </div>
            </div>
          </details>
          <div className="flex justify-end gap-2 border-t pt-4">
            <Button type="button" variant="outline" disabled={busy} onClick={close}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={!valid || busy}>
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
  );
}
