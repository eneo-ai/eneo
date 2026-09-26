"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import {
  initialServiceKeySelection,
  listCompatibleServiceKeys,
  parseRedirectUris,
  serviceKeyLabel,
  type ModuleInstallation
} from "./modules";

const UNBOUND = "__unbound__";

export function ModulesPage({ title }: { title: string }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const formRef = useRef<HTMLFormElement>(null);
  const [moduleKey, setModuleKey] = useState("");
  const [redirectUrisInput, setRedirectUrisInput] = useState("");
  const [serviceKeyId, setServiceKeyId] = useState("");
  const [boundKeyMissing, setBoundKeyMissing] = useState(false);
  const [editingModuleKey, setEditingModuleKey] = useState<string | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<ModuleInstallation | null>(null);
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState(false);

  const installations = useQuery({
    queryKey: ["admin-modules"],
    queryFn: async () => (await unwrap(browserApi.GET("/api/v1/admin/modules/"))).items
  });
  const serviceKeys = useQuery({
    queryKey: ["module-compatible-service-keys"],
    queryFn: listCompatibleServiceKeys
  });
  const loading = installations.isPending || serviceKeys.isPending;
  const loadError = installations.error ?? serviceKeys.error;
  const keys = serviceKeys.data ?? [];
  const redirectUris = parseRedirectUris(redirectUrisInput);

  useEffect(() => {
    if (loadError) toastApiError(loadError, t);
  }, [loadError, t]);

  function resetForm() {
    setModuleKey("");
    setRedirectUrisInput("");
    setServiceKeyId("");
    setBoundKeyMissing(false);
    setEditingModuleKey(null);
  }

  function editInstallation(installation: ModuleInstallation) {
    setModuleKey(installation.module_key);
    setRedirectUrisInput((installation.redirect_uris ?? []).join("\n"));
    const selected = initialServiceKeySelection(installation, keys);
    setServiceKeyId(selected.selection);
    setBoundKeyMissing(selected.missing);
    setEditingModuleKey(installation.module_key);
    formRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function saveInstallation(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const key = moduleKey.trim();
    if (!key || redirectUris.length === 0 || !serviceKeyId) return;
    setSaving(true);
    try {
      await unwrap(
        browserApi.PUT("/api/v1/admin/modules/{module_key}/", {
          params: { path: { module_key: key } },
          body: {
            redirect_uris: redirectUris,
            service_key_id: serviceKeyId === UNBOUND ? null : serviceKeyId
          }
        })
      );
      toast.success(t("module_admin_saved"));
      resetForm();
      await queryClient.invalidateQueries({ queryKey: ["admin-modules"] });
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setSaving(false);
    }
  }

  async function removeInstallation() {
    if (!pendingRemoval) return;
    const removedKey = pendingRemoval.module_key;
    setRemoving(true);
    try {
      await unwrap(
        browserApi.DELETE("/api/v1/admin/modules/{module_key}/", {
          params: { path: { module_key: removedKey } }
        })
      );
      toast.success(t("module_admin_removed"));
      setPendingRemoval(null);
      if (editingModuleKey === removedKey) resetForm();
      await queryClient.invalidateQueries({ queryKey: ["admin-modules"] });
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
      <PageHeader title={title} tour="admin-modules" />
      <section className="space-y-4" aria-labelledby="installed-modules-title">
        <div>
          <h2 id="installed-modules-title" className="text-lg font-semibold">
            {t("module_admin_installed_title")}
          </h2>
          <p className="text-muted-foreground mt-1 text-sm">{t("module_admin_description")}</p>
        </div>
        {loadError && (
          <Alert variant="destructive" role="alert">
            <CircleAlert className="size-4" />
            <AlertDescription>{loadError.message}</AlertDescription>
          </Alert>
        )}
        {loading ? (
          <div className="space-y-3" aria-label={t("loading")}>
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : (installations.data ?? []).length === 0 ? (
          <div className="rounded-lg border border-dashed px-6 py-10 text-center">
            <p className="font-medium">{t("module_admin_empty_title")}</p>
            <p className="text-muted-foreground mt-1 text-sm">
              {t("module_admin_empty_description")}
            </p>
          </div>
        ) : (
          <ul className="grid gap-3">
            {(installations.data ?? []).map((installation) => {
              const boundKey = keys.find((key) => key.id === installation.service_key_id);
              return (
                <li key={installation.module_id} className="rounded-lg border p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <h3 className="font-mono text-sm font-semibold">{installation.module_key}</h3>
                      <Badge variant={installation.configured ? "default" : "destructive"}>
                        {installation.configured
                          ? t("module_admin_configured")
                          : t("module_admin_incomplete")}
                      </Badge>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => editInstallation(installation)}
                      >
                        <Pencil className="size-4" /> {t("edit")}
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => setPendingRemoval(installation)}
                      >
                        <Trash2 className="size-4" /> {t("remove")}
                      </Button>
                    </div>
                  </div>
                  <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
                    <div className="min-w-0">
                      <dt className="text-muted-foreground">{t("module_admin_callback_urls")}</dt>
                      <dd className="mt-1 space-y-1">
                        {(installation.redirect_uris ?? []).length > 0
                          ? installation.redirect_uris?.map((uri) => (
                              <div key={uri} className="truncate" title={uri}>
                                {uri}
                              </div>
                            ))
                          : "—"}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-muted-foreground">{t("module_admin_service_key")}</dt>
                      <dd className="mt-1">
                        {boundKey
                          ? serviceKeyLabel(boundKey)
                          : installation.service_key_id
                            ? `${installation.service_key_id.slice(0, 8)}…`
                            : "—"}
                      </dd>
                    </div>
                  </dl>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="space-y-4 border-t pt-6" aria-labelledby="module-form-title">
        <h2 id="module-form-title" className="text-lg font-semibold">
          {t(editingModuleKey ? "module_admin_edit_title" : "module_admin_add_title")}
        </h2>
        <form ref={formRef} className="max-w-2xl space-y-5" onSubmit={saveInstallation}>
          <div className="space-y-2">
            <Label htmlFor="module-key">{t("module_admin_module_key")}</Label>
            <Input
              id="module-key"
              value={moduleKey}
              onChange={(event) => setModuleKey(event.target.value)}
              required
              disabled={editingModuleKey !== null || saving}
              pattern="[A-Za-z0-9][A-Za-z0-9._-]*"
              autoComplete="off"
              placeholder={t("module_admin_module_key_placeholder")}
            />
            <p className="text-muted-foreground text-sm">{t("module_admin_module_key_help")}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="redirect-uris">{t("module_admin_callback_urls")}</Label>
            <Textarea
              id="redirect-uris"
              value={redirectUrisInput}
              onChange={(event) => setRedirectUrisInput(event.target.value)}
              required
              disabled={saving}
              rows={4}
              placeholder={t("module_admin_callback_urls_placeholder")}
            />
            <p className="text-muted-foreground text-sm">{t("module_admin_callback_urls_help")}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="service-key">{t("module_admin_service_key")}</Label>
            <select
              id="service-key"
              value={serviceKeyId}
              onChange={(event) => {
                setServiceKeyId(event.target.value);
                setBoundKeyMissing(false);
              }}
              required
              disabled={saving || loading}
              className="bg-background border-input focus-visible:ring-ring h-9 w-full rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:outline-none"
            >
              <option value="" disabled>
                {t("module_admin_service_key_placeholder")}
              </option>
              <option value={UNBOUND}>{t("module_admin_service_key_unbound")}</option>
              {keys.map((key) => (
                <option key={key.id} value={key.id}>
                  {serviceKeyLabel(key)}
                </option>
              ))}
            </select>
            <p className="text-muted-foreground text-sm">{t("module_admin_service_key_help")}</p>
            {boundKeyMissing && !serviceKeyId && (
              <Alert variant="destructive" role="alert">
                <CircleAlert className="size-4" />
                <AlertDescription>{t("module_admin_bound_key_missing")}</AlertDescription>
              </Alert>
            )}
          </div>
          {!loading && keys.length === 0 && (
            <Alert>
              <CircleAlert className="size-4" />
              <AlertTitle>{t("module_admin_no_service_keys_title")}</AlertTitle>
              <AlertDescription>
                {t("module_admin_no_service_keys_description")}{" "}
                <Link className="underline" href="/admin/api-keys">
                  {t("module_admin_manage_service_keys")}
                </Link>
              </AlertDescription>
            </Alert>
          )}
          <div className="flex gap-2">
            <Button
              type="submit"
              disabled={
                saving || loading || !moduleKey.trim() || !redirectUris.length || !serviceKeyId
              }
            >
              <Plus className="size-4" />
              {t(editingModuleKey ? "module_admin_update" : "module_admin_install")}
            </Button>
            {editingModuleKey && (
              <Button type="button" variant="outline" disabled={saving} onClick={resetForm}>
                {t("cancel")}
              </Button>
            )}
          </div>
        </form>
      </section>
      <ConfirmDialogControlled
        open={pendingRemoval !== null}
        onOpenChange={(open) => {
          if (!open && !removing) setPendingRemoval(null);
        }}
        title={t("module_admin_remove_title")}
        description={t("module_admin_remove_description", {
          moduleKey: pendingRemoval?.module_key ?? ""
        })}
        confirmLabel={removing ? t("removing") : t("remove")}
        pending={removing}
        onConfirm={() => void removeInstallation()}
      />
    </div>
  );
}
